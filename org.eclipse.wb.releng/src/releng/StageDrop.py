"""
Python script to stage a drop of WindowBuilder
"""
import datetime
import eclipse
import glob
import logging
import logging.config
import os
import Queue
import re
import shutil
import stat
import subprocess
import sys
import util
import zipfile 

from optparse import OptionParser
from time import sleep
from datetime import datetime, time, date

logging.config.fileConfig('logger.config')

log = logging.getLogger("releng")
log.info("starting StageDrop.py")

def main():
  log.debug("in main")
  data = processArgs()
  dropLocation = data['droplocation']
  subproduct = data['subproduct']
  signDir = data['signdir']
  eclipseVersion = data['eclipseversion']
  optimizeSite = data['optimizesite']
  packSite = data['packsite']
  signFiles = data['signfiles']  
  doDeploy = data['dodeploy']
  deployDir = data['deploydir']
  dirs2save = data['dirstosave']
  
  baseDir = os.path.join(os.sep + "shared", "tools", "windowbuilder", "stage")
  productDir = os.path.join(baseDir, subproduct);
  
  if not doDeploy:
    log.info("Initialize " + signDir)

    try:
      os.mkdir(baseDir)
    except OSError as e:
      if e.errno != 17:
        log.error("could not create " + baseDir)
        raise e
      
    rmDirTree(signDir)
    rmDirTree(baseDir)
    os.mkdir(productDir)
    
    log.info("Copy files from " + dropLocation + " to " + productDir)
    copyFiles(dropLocation, productDir, filesOnly)
    
    log.info("Move zip files from " + productDir + " to " + signDir)
    moveFiles(productDir, signDir, zipFilter)
    
    if optimizeSite:
      log.info("Optimize Site")
      optimizedDir = eclipse.optimizeSite(baseDir, signDir, eclipseVersion)
      copyFiles(optimizedDir, signDir, None)
      rmDirTree(optimizedDir)
      os.rmdir(optimizedDir)
      
    if signFiles:
      log.info("Sign files")
      signedDir = signZipFiles(signDir)
      copyFiles(signedDir, signDir, None)
      rmDirTree(signedDir)
      os.rmdir(signedDir)
  
    if packSite:
      log.info("pack Site")
      packDir = eclipse.packSite(baseDir, signDir, eclipseVersion)
      copyFiles(packDir, signDir, None)
      rmDirTree(packDir)
      os.rmdir(packDir)
    log.info("Move signed files from " + signDir + " to " + productDir)
    moveFiles(signDir, productDir, None)
    
    log.info("Unzip the signed files")
    unzipSites(productDir)

    log.info("UpdateMirror")
    updateMirror(productDir)
    
    log.info("Generate Eclipse P2 Metadata")
    eclipse.publishSite(baseDir, productDir, eclipseVersion)
  
    log.info("rezip Site")
    rezipSite(productDir)
    
    log.info("update MD5 files")
    util.updateMd5Hash(productDir)
  else:
    log.info("doing deployment")
    log.info("deploy code")
    deployCode(productDir, deployDir)

  log.info("cleanup")
  cleanup(signDir, deployDir, dirs2save)
  
  log.debug("done main")
  

def zipFilter(file):
  return file.endswith('.zip')

def zipOrMd5Filter(file):
  return file.endswith('.zip') or file.endswith('.MD5')

def filesOnly(file):
  return os.path.isfile(file)

def processArgs():
  signDir = os.path.join(os.sep + "home", "data", "httpd", 
                         "download-staging.priv", "tools", "windowbuilder")
  deployDir = os.path.join(os.sep + 'home', 'data', 'httpd', 
                           'download.eclipse.org', 'windowbuilder')
  usage = "usage: %prog [options] drop subproduct"
  parser = OptionParser(usage=usage)
  parser.set_defaults(debug=False)
  parser.set_defaults(eclipseversion="3.7")
  parser.set_defaults(optimizesite=True)
  parser.set_defaults(packsite=True)
  parser.set_defaults(signfiles=True)
  parser.set_defaults(dodeploy=False)
  parser.set_defaults(dirstosave="7")
  parser.add_option("--signdir", action="store", dest="signdir")
  parser.add_option("-e", "--eclipseversion", action="store", 
                    dest="eclipseversion")
  parser.add_option("--eclipsearchivedir", action="store", 
                    dest="eclipsearchivedir")
  parser.add_option("--nooptimizesite", action="store_false", dest="optimizesite");
  parser.add_option("--nopacksite", action="store_false", dest="packsite")
  parser.add_option("--nosignfiles", action="store_false", dest="signfiles")
  parser.add_option("--deployfiles", action="store_true", dest="dodeploy")
  parser.add_option("--deploydir", action="store", dest="deploydir")
  parser.add_option("--dirstosave", action="store", dest="dirstosave")
  (options, args) = parser.parse_args()
  
  if len(args) != 2:
    parser.error("incorrect number of arguments")
    
  optimizeSite = options.optimizesite
  packSite = options.packsite
  signFiles = options.signfiles
  doDeploy = options.dodeploy
  dirs2save = int(options.dirstosave)


  if options.signdir != None:
    signDir = options.signdir

  if options.deploydir != None:
    deployDir = options.deploydir
  
  if options.eclipsearchivedir != None:
    eclipse.setArchiveDir(options.eclipsearchivedir)
    
  eclipseVersion = options.eclipseversion
       
  dropLocation = args[0]
  subproduct = args[1]

  deployDir = os.path.join(deployDir, subproduct);
  
  if dropLocation == None:
    log.error("you must specify a drop location")
    usage()
    sys.exit(20)

  if subproduct == None:
    log.error("you must specify a subproduct")
    usage()
    sys.exit(21)
    
  if doDeploy:
    optimizeSite = False
    packSite = False
    signFiles = False
    
  
  ret = dict({'droplocation':dropLocation, 'subproduct':subproduct, 
              'signdir':signDir, 'eclipseversion':eclipseVersion,
              'optimizesite':optimizeSite, 'packsite':packSite,
              'signfiles':signFiles, 'dodeploy':doDeploy,
              'deploydir':deployDir, 'dirstosave':dirs2save})
  log.debug("out of processArgs")
  return ret

def rmDirTree(top):
  # Delete everything reachable from the directory named in "top",
  # assuming there are no symbolic links.
  # CAUTION:  This is dangerous!  For example, if top == '/', it
  # could delete all your disk files.
  log.debug("rmDirTree(" + top + ")")
  log.info("removing " + top + " directory tree")
  if top == "/":
    log.critical("can not pass / as the top directory")
    return
  
  for root, dirs, files in os.walk(top, topdown=False):
    for name in files:
        os.remove(os.path.join(root, name))
    for name in dirs:
        os.rmdir(os.path.join(root, name))
  return

def copyFiles(fromDir, toDir, filter):
  log.debug("copyFiles(" + fromDir + ", " + toDir)
  try:
    files = os.listdir(fromDir);
  except OSError as e:
    log.error("could not read files in " + fromDir);
    raise e
  
  if len(files) == 0:
    raise OSError("no files to process")
  
  for file in files:
    fullPath = os.path.join(fromDir, file)
    if (filter == None or filter(fullPath)):
      shutil.copy2(fullPath, toDir)
    
def moveFiles(fromDir, toDir, filter):
  log.debug("moveFiles(" + fromDir + ", " + toDir)
  try:
    files = os.listdir(fromDir);
  except OSError as e:
    log.error("could not read files in " + fromDir);
    raise e
  
  if len(files) == 0:
    raise OSError("no files to process")
  
  for file in files:
    fullPath = os.path.join(fromDir, file)
    if (filter == None or filter(fullPath)):
      shutil.move(fullPath, toDir)
    
def signZipFiles(dir):
  log.debug("signFiles(" + dir + ")")
  
  try:
    files = os.listdir(dir);
  except OSError as e:
    log.error("could not read files in " + dir);
    raise e
  
  filesToSign = []
  for file in files:
    if file.endswith('.zip'):
      zipPath = os.path.join(dir, file)
      os.chmod(zipPath, stat.S_IWRITE | stat.S_IREAD | stat.S_IWGRP | 
               stat.S_IRGRP | stat.S_IWOTH | stat.S_IROTH)
#      subprocess.check_call(['/bin/echo', 'sign', zipPath, 'nomail', 'signed'])
      subprocess.check_call(['/usr/local/bin/sign', zipPath, 'nomail', 'signed'])
      filesToSign.append(os.path.join(dir, "signed", file))

  signedFiles = []
  found = False;
  while(not found):
    found = True
    for x in range(60):
      sleep(1)
    for file in filesToSign:
      if (os.path.exists(file)):
        log.debug(file + " exists")
        signedFiles.append(file)
      else:
        found = False
        log.debug(file + " does not exists")
        continue
    log.info("all files are not processed yet")
        
  sleep(10)
  log.info("all files have been signed")
  return os.path.join(dir, "signed")

from xml.dom import minidom
def unzipSites(dir):
  log.debug("unzipSites(" + dir + ")")
  try:
    files = os.listdir(dir);
  except OSError as e:
    log.error("could not read files in " + dir);
    raise e
  versionRE = re.compile('.+Eclipse([0-9]\.[0-9]).+')
  
  for file in files:
    res = versionRE.search(file)
    util.__displaymatch(res)
    version = res.group(1)
    unarchiveDest = os.path.join(dir, version)
    if not os.path.exists(unarchiveDest):
      os.mkdir(unarchiveDest)
      
    util.unarchive(os.path.join(dir, file), unarchiveDest)

def rezipSite(dir):
  log.debug("rezipSite(" + dir + ")")
  formatDir =  'D: {0:<120} N: {1}'
  formatFile = 'F: {0:<120} N: {1}'
  formatZip = '{0:<70} {1:>9} {2:>9}'
  try:
    files = os.listdir(dir);
  except OSError as e:
    log.error("could not read files in " + dir);
    raise e
  versionRE = re.compile('.+Eclipse([0-9]\.[0-9]).+')
  
  for file in files:
    if file.endswith('.zip'):
      zipFile = os.path.join(dir, file)
      log.info("processing " + zipFile)
      res = versionRE.search(file)
      util.__displaymatch(res)
      version = res.group(1)
      siteDir = os.path.join(dir, version)

      log.debug("removing " + zipFile)
      os.remove(zipFile)
      log.debug("creating zip file " + zipFile)
      cwd = os.getcwd()
      os.chdir(siteDir)
      log.debug('creating zip in ' + os.getcwd())
      command = ['zip', zipFile]

      for root, dirs, files in os.walk(siteDir, followlinks=False):
        for name in files:
          fileToZip = os.path.join(root, name)
          zipFileName = fileToZip[len(siteDir)+1:]
          log.debug(formatFile.format(fileToZip, zipFileName))
          if not zipFileName.endswith('pack.gz'):
            command.append(zipFileName)
            
      if log.debug:
        data = "Command: "
        for cmd in command:
          data = data + cmd + ' '
        log.debug(data)

      subprocess.check_call(command)
      # open the file again, to see what's in it
      if (log.debug):
        zip = zipfile.ZipFile(zipFile, "r")
        for info in zip.infolist():
          log.debug(formatZip.format(info.filename, info.file_size, info.compress_size))
    log.debug("out rezipSite")

def deployCode(fromDir, toDir):
  log.debug("in deployCode(" + fromDir + ", " + toDir+ ")")
  deployDir = toDir
  try:
    os.mkdir(deployDir)
  except OSError as e:
    if e.errno != 17:
      log.error("failed to make directory " + str(deployDir) + ": " + str(e));
      raise e

  latestDir = os.path.join(deployDir, 'integration')
  d = datetime.today()
  nowString = d.strftime('%Y%m%d%H%M')
  dateDir = os.path.join(deployDir, nowString)
  deployDirs = [latestDir, dateDir]
  log.info("deploying to ")
  log.info(latestDir)
  log.info('and')
  log.info(dateDir)
  log.debug("out deployCode")
  rmDirTree(latestDir);
  for file in deployDirs:
    try:
      os.mkdir(file)
    except OSError as e:
      if e.errno != 17:
        log.error("failed to make directory " + str(file) + ": " + str(e));
        raise e

    sourceFiles = glob.glob(os.path.join(fromDir, '*'))
    command = ['rsync', '-av']
    for sfile in sourceFiles:
      command.append(sfile)
    command.append(file)
           
    if log.debug:
      data = "Command: "
      for cmd in command:
        data = data + cmd + ' '
      log.debug(data)

      subprocess.check_call(command)
   

def cleanup(signDir, deployDir, dirsToSave):
  log.debug("in cleanup(" + signDir + ", " + deployDir + ", " + 
            str(dirsToSave) + ")")
  rmDirTree(signDir);
  
  
  pq = Queue.PriorityQueue()
  try:
    for file in os.listdir(deployDir):
      pq.put(file)
  except OSError as e:
    log.warn("could not read files in " + deployDir);
    
  dirsToDelete = pq.qsize()
  dirsToDelete -= dirsToSave + 1
  dirCount = 0
  while not pq.empty():
    dir = os.path.join(deployDir, pq.get())
    dirCount += 1;
    if dirCount <= dirsToDelete:
      print "deleting -> " + dir
      rmDirTree(dir)
      os.rmdir(dir)
    else:
      print "saving  ->  " + dir
  log.debug("out cleanup")

def updateMirror(dir):
  log.debug("in updateMirror(" + dir + ")")
  fullFile = os.path.join(dir, '3.7');
  if os.path.exists(fullFile):
    file = os.path.join(fullFile, 'site.xml')
    log.debug('processing ' + file)
    dom = minidom.parse(file)
    attr = dom.createAttribute('mirrorsURL')
    site = dom.documentElement
    attr.value = "http://www.eclipse.org/downloads/download.php?file=/windowbuilder/WB/release/R201106211200/3.7&format=xml"
    site.setAttributeNode(attr)
    f = open(file, 'w')
    site.writexml( f, addindent="   ")
    f.close()

    
  log.debug("out updateMirror()")
  
if __name__ == "__main__":
  main()
  
  log.info("StageDrop.py is done")
