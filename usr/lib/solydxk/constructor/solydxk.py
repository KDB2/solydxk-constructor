#! /usr/bin/env python3

import re
import threading
from os import remove, rmdir, makedirs, system, listdir
from shutil import copy, move
from datetime import datetime
from execcmd import ExecCmd
from os.path import join, exists, basename, abspath, dirname, lexists, isdir


class IsoUnpack(threading.Thread):

    def __init__(self, mountDir, unpackIso, unpackDir, queue):
        threading.Thread.__init__(self)
        self.ec = ExecCmd()
        self.mountDir = mountDir
        self.unpackIso = unpackIso
        self.unpackDir = unpackDir
        self.queue = queue
        self.returnMessage = None

    def run(self):
        try:
            if not exists(self.mountDir):
                print(("Create mount directory: %s" % self.mountDir))
                makedirs(self.mountDir)

            rootDir = join(self.unpackDir, "root")
            if not exists(rootDir):
                print(("Create root directory: %s" % rootDir))
                makedirs(rootDir)

            isolinuxDir = join(self.unpackDir, "boot/isolinux")
            if not exists(isolinuxDir):
                print(("Create isolinux directory: %s" % isolinuxDir))
                makedirs(isolinuxDir)

            liveDir = join(self.unpackDir, "boot/live")
            if not exists(liveDir):
                print(("Create liveDir directory: %s" % liveDir))
                makedirs(liveDir)

            # Mount the ISO
            system("mount -o loop '%s' '%s'" % (self.unpackIso, self.mountDir))

            # Check isolinux directory
            mountIsolinux = join(self.mountDir, "isolinux")
            if not exists(mountIsolinux):
                self.ec.run("umount --force '%s'" % self.mountDir)
                self.returnMessage = "ERROR: Cannot find isolinux directory in ISO"

            fixCfgCmd = None
            dirs = []
            mountSquashfs = None
            if self.returnMessage is None:
                subdirs = self.getDirectSubDirectories(self.mountDir)
                for subdir in subdirs:
                    if self.hasSquashFs(join(self.mountDir, subdir)):
                        mountSquashfs = join(self.mountDir, subdir)
                        if subdir != "live":
                            fixCfgCmd = "sed -i 's/\/%s/\/live/g' %s/isolinux.cfg" % (subdir, isolinuxDir)
                    elif subdir != "isolinux":
                        dirs.append(join(self.mountDir, subdir))

                if mountSquashfs is None:
                    self.ec.run("umount --force '%s'" % self.mountDir)
                    self.returnMessage = "ERROR: Cannot find squashfs directory in ISO"

            if self.returnMessage is None:
                # Copy files from ISO to unpack directory
                for d in dirs:
                    self.ec.run("rsync -at --del '%s' '%s'" % (d, join(self.unpackDir, "boot/")))
                self.ec.run("rsync -at --del '%s/' '%s'" % (mountIsolinux, isolinuxDir))
                self.ec.run("rsync -at --del '%s/' '%s'" % (mountSquashfs, liveDir))
                self.ec.run("umount --force '%s'" % self.mountDir)

                if fixCfgCmd is not None:
                    self.ec.run(fixCfgCmd)

                # copy squashfs root
                squashfs = join(liveDir, "filesystem.squashfs")
                if exists(squashfs):
                    self.ec.run("mount -t squashfs -o loop '%s' '%s'" % (squashfs, self.mountDir))
                    self.ec.run("rsync -at --del '%s/' '%s/'" % (self.mountDir, rootDir))
                    self.ec.run("umount --force '%s'" % self.mountDir)

                # Cleanup
                rmdir(self.mountDir)
                # set proper permissions
                self.ec.run("chmod 6755 '%s'" % join(rootDir, "usr/bin/sudo"))
                self.ec.run("chmod 0440 '%s'" % join(rootDir, "etc/sudoers"))

                self.returnMessage = "DONE - ISO unpacked to: %s" % self.unpackDir

            self.queue.put(self.returnMessage)

        except Exception as detail:
            self.ec.run("umount --force '%s'" % self.mountDir)
            rmdir(self.mountDir)
            self.returnMessage = "ERROR: IsoUnpack: %(detail)s" % {"detail": detail}
            self.queue.put(self.returnMessage)

    def getDirectSubDirectories(self, directory):
        subdirs = []
        names = listdir(directory)
        for name in names:
            if isdir(join(directory, name)):
                subdirs.append(name)
        return subdirs

    def hasSquashFs(self, directory):
        names = listdir(directory)
        for name in names:
            if name == "filesystem.squashfs":
                return True
        return False


class BuildIso(threading.Thread):

    def __init__(self, distroPath, queue):
        threading.Thread.__init__(self)
        self.ec = ExecCmd()
        self.dg = DistroGeneral(distroPath)
        self.ed = EditDistro(distroPath)
        self.queue = queue

        self.returnMessage = None

        # Paths
        distroPath = distroPath.rstrip('/')
        if basename(distroPath) == "root":
            distroPath = dirname(distroPath)
        self.distroPath = distroPath
        self.rootPath = join(distroPath, "root")
        self.bootPath = join(distroPath, "boot")
        self.livePath = join(self.bootPath, "live")
        self.scriptDir = abspath(dirname(__file__))

        # Check for old dir
        oldDir = join(self.bootPath, "solydxk")
        if exists(oldDir):
            self.ec.run("rm -r %s" % oldDir)

        # Make sure live directory exists
        if not exists(self.livePath):
            self.ec.run("mkdir -p %s" % self.livePath)

        # ISO Name
        self.isoName = self.dg.description

        # ISO distribution
        self.isoBaseName = self.dg.getIsoFileName()
        self.isoFileName = join(self.distroPath, self.isoBaseName)

        # Trackers, and webseeds
        self.trackers = ""
        self.webseeds = ""
        trackersPath = join(self.scriptDir, "files/trackers")
        webseedsPath = join(self.scriptDir, "files/webseeds")
        if exists(trackersPath):
            with open(trackersPath, "r") as f:
                lines = f.readlines()
                trList = []
                for line in lines:
                    trList.append(line.strip())
                self.trackers = ",".join(trList)
        if exists(webseedsPath):
            with open(webseedsPath, "r") as f:
                lines = f.readlines()
                wsList = []
                for line in lines:
                    #wsList.append("%s/%s" % (line.strip(), webseedIsoName))
                    wsList.append("%s/%s" % (line.strip(), self.isoBaseName))
                self.webseeds = ",".join(wsList)

    def run(self):
        try:
            if not exists(self.rootPath):
                self.returnMessage = "ERROR: Cannot find root directory: %s" % self.rootPath

            if not exists(self.bootPath):
                self.returnMessage = "ERROR: Cannot find boot directory: %s" % self.bootPath

            if self.returnMessage is None:
                print("======================================================")
                print("INFO: Cleanup and prepare ISO build...")
                print("======================================================")

                # Clean-up
                script = "cleanup.sh"
                scriptSource = join(self.scriptDir, "files/{}".format(script))
                scriptTarget = join(self.rootPath, script)
                if exists(scriptSource):
                    self.copy_file(scriptSource, scriptTarget)
                    self.ec.run("chmod a+x %s" % scriptTarget)
                    plymouthTheme = self.dg.getPlymouthTheme()
                    #self.ec.run("chroot '%(rootPath)s' /bin/bash %(cleanup)s %(plymouthTheme)s" % {"rootPath": self.rootPath, "cleanup": cleanup, "plymouthTheme": plymouthTheme})
                    cmd = "/bin/bash %(cleanup)s %(plymouthTheme)s" % {"cleanup": script, "plymouthTheme": plymouthTheme}
                    self.ed.openTerminal(cmd)
                    remove(scriptTarget)

                rootHome = join(self.rootPath, "root")
                nanoHist = join(rootHome, ".nano_history")
                if exists(nanoHist):
                    remove(nanoHist)
                bashHist = join(rootHome, ".bash_history")
                if exists(bashHist):
                    remove(bashHist)

                # Config naming
                regExp = "solyd.*(\d{6}|-bit)"
                d = datetime.now()
                dateString = d.strftime("%Y%m")
                nameString = "{} {}".format(self.isoName, dateString)

                # write iso name to boot/isolinux/isolinux.cfg
                cfgFile = join(self.bootPath, "isolinux/isolinux.cfg")
                if exists(cfgFile):
                    content = ""
                    with open(cfgFile, 'r') as f:
                        content = f.read()
                    if content != "":
                        content = re.sub(regExp, nameString, content, flags=re.IGNORECASE)
                        # Make sure that the paths are correct (correcting very old stuff)
                        content = re.sub('.lz', '.img', content)
                        content = re.sub('/solydxk/', '/live/', content)
                        with open(cfgFile, 'w') as f:
                            f.write(content)

                # Write info for grub (EFI)
                grubFile = join(self.bootPath, "boot/grub/grub.cfg")
                if exists(grubFile):
                    content = ""
                    with open(grubFile, 'r') as f:
                        content = f.read()
                    if content != "":
                        content = re.sub(regExp, nameString, content, flags=re.IGNORECASE)
                        with open(grubFile, 'w') as f:
                            f.write(content)

                loopbackFile = join(self.bootPath, "boot/grub/loopback.cfg")
                if exists(loopbackFile):
                    content = ""
                    with open(loopbackFile, 'r') as f:
                        content = f.read()
                    if content != "":
                        content = re.sub(regExp, nameString, content, flags=re.IGNORECASE)
                        with open(loopbackFile, 'w') as f:
                            f.write(content)

                # Clean boot/live directory
                #popen("rm -rf %s/live/*" % self.bootPath)

                # Vmlinuz
                vmlinuzSymLink = join(self.distroPath, "root/vmlinuz")
                if lexists(vmlinuzSymLink):
                    vmlinuzFile = self.ec.run("ls -al %s | cut -d'>' -f2" % vmlinuzSymLink)[0].strip()
                else:
                    self.returnMessage = "ERROR: %s not found" % vmlinuzSymLink

            if self.returnMessage is None:
                vmlinuzPath = join(self.distroPath, "root/%s" % vmlinuzFile)
                if exists(vmlinuzPath):
                    print("Copy vmlinuz")
                    self.copy_file(vmlinuzPath, join(self.livePath, "vmlinuz"))
                else:
                    self.returnMessage = "ERROR: %s not found" % vmlinuzPath

            if self.returnMessage is None:
                # Initrd
                initrdSymLink = join(self.distroPath, "root/initrd.img")
                if lexists(initrdSymLink):
                    initrdFile = self.ec.run("ls -al %s | cut -d'>' -f2" % initrdSymLink)[0].strip()
                else:
                    self.returnMessage = "ERROR: %s not found" % initrdSymLink

            if self.returnMessage is None:
                initrdPath = join(self.distroPath, "root/%s" % initrdFile)
                if exists(initrdPath):
                    print("Copy initrd")
                    self.copy_file(initrdPath, join(self.livePath, "initrd.img"))
                else:
                    self.returnMessage = "ERROR: %s not found" % initrdPath

            if self.returnMessage is None:
                # Generate UUID
                #diskDir = join(self.bootPath, ".disk")
                #if not exists(diskDir):
                    #makedirs(diskDir)
                #self.ec.run("rm -rf %s/*uuid*" % diskDir)
                #self.ec.run("uuidgen -r > %s/live-uuid-generic" % diskDir)
                #copy_file(join(diskDir, "live-uuid-generic"), join(diskDir, "live-uuid-generic"))

                #Update filesystem.size
                #self.ec.run("du -b %(directory)s/root/ 2> /dev/null | tail -1 | awk {'print $1;'} > %(directory)s/live/filesystem.size" % {"directory": self.bootPath})

                print("======================================================")
                print("INFO: Start building ISO...")
                print("======================================================")

                # build squash root
                print("Creating SquashFS root...")
                print("Updating File lists...")
                dpkgQuery = ' dpkg -l | awk \'/^ii/ {print $2, $3}\' | sed -e \'s/ /\t/g\' '
                self.ec.run('chroot \"' + self.rootPath + '\"' + dpkgQuery + ' > \"' + join(self.livePath, "filesystem.packages") + '\"' )
                #dpkgQuery = ' dpkg-query -W --showformat=\'${Package} ${Version}\n\' '
                #self.ec.run('chroot \"' + self.rootPath + '\"' + dpkgQuery + ' > \"' + join(self.bootPath, "live/filesystem.manifest") + '\"' )
                #copy_file(join(self.bootPath, "live/filesystem.manifest"), join(self.bootPath, "live/filesystem.manifest-desktop"))
                # check for existing squashfs root
                if exists(join(self.livePath, "filesystem.squashfs")):
                    print("Removing existing SquashFS root...")
                    remove(join(self.livePath, "filesystem.squashfs"))
                print("Building SquashFS root...")
                # check for alternate mksquashfs
                # check for custom mksquashfs (for multi-threading, new features, etc.)
                mksquashfs = self.ec.run(cmd="echo $MKSQUASHFS", returnAsList=False).strip()
                rootPath = join(self.distroPath, "root/")
                squashfsPath = join(self.livePath, "filesystem.squashfs")
                if mksquashfs == '' or mksquashfs == 'mksquashfs':
                    try:
                        nrprocessors = int(int(self.ec.run("nproc", False, False))/2)
                        if nrprocessors < 1:
                            nrprocessors = 1
                    except:
                        nrprocessors = 1
                    cmd = "mksquashfs \"{}\" \"{}\" -comp xz -processors {}".format(rootPath, squashfsPath, nrprocessors)
                else:
                    cmd = "{} \"{}\" \"{}\"".format(mksquashfs, rootPath, squashfsPath)
                #print(cmd)
                self.ec.run(cmd)

                # build iso
                print("Creating ISO...")
                # update manifest files
                #self.ec.run("/usr/lib/solydxk/constructor/updateManifest.sh %s" % self.distroPath)
                # update md5
                print("Updating md5 sums...")
                if exists(join(self.bootPath, "md5sum.txt")):
                    remove(join(self.bootPath, "md5sum.txt"))
                if exists(join(self.bootPath, "MD5SUMS")):
                    remove(join(self.bootPath, "MD5SUMS"))
                self.ec.run('cd \"' + self.bootPath + '\"; ' + 'find . -type f -print0 | xargs -0 md5sum > md5sum.txt')
                #Remove md5sum.txt, MD5SUMS, boot.cat and isolinux.bin from md5sum.txt
                self.ec.run("sed -i '/md5sum.txt/d' %s/md5sum.txt" % self.bootPath)
                self.ec.run("sed -i '/MD5SUMS/d' %s/md5sum.txt" % self.bootPath)
                self.ec.run("sed -i '/boot.cat/d' %s/md5sum.txt" % self.bootPath)
                self.ec.run("sed -i '/isolinux.bin/d'  %s/md5sum.txt" % self.bootPath)
                #Copy md5sum.txt to MD5SUMS (for Debian compatibility)
                self.copy_file(join(self.bootPath, "md5sum.txt"), join(self.bootPath, "MD5SUMS"))

                # Update isolinux files
                syslinuxPath = join(self.rootPath, "usr/lib/syslinux")
                modulesPath = join(syslinuxPath, "modules/bios")
                isolinuxPath = join(self.bootPath, "isolinux")
                self.ec.run("chmod -R +w {}".format(isolinuxPath))
                cat = join(isolinuxPath, "boot.cat")
                if exists(cat):
                    remove(cat)
                self.copy_file(join(modulesPath, "chain.c32"), isolinuxPath)
                self.copy_file(join(modulesPath, "hdt.c32"), isolinuxPath)
                self.copy_file(join(modulesPath, "libmenu.c32"), isolinuxPath)
                self.copy_file(join(modulesPath, "libgpl.c32"), isolinuxPath)
                self.copy_file(join(modulesPath, "reboot.c32"), isolinuxPath)
                self.copy_file(join(modulesPath, "vesamenu.c32"), isolinuxPath)
                self.copy_file(join(modulesPath, "poweroff.c32"), isolinuxPath)
                self.copy_file(join(modulesPath, "ldlinux.c32"), isolinuxPath)
                self.copy_file(join(modulesPath, "libcom32.c32"), isolinuxPath)
                self.copy_file(join(modulesPath, "libutil.c32"), isolinuxPath)
                self.copy_file(join(self.rootPath, "boot/memtest86+.bin"), join(isolinuxPath, "memtest86"))
                self.copy_file("/usr/lib/ISOLINUX/isolinux.bin", isolinuxPath)

                # remove existing iso
                if exists(self.isoFileName):
                    print("Removing existing ISO...")
                    remove(self.isoFileName)

                # build iso according to architecture
                print("Building ISO...")
                self.ec.run('genisoimage -input-charset utf-8 -o \"' + self.isoFileName + '\" -b \"isolinux/isolinux.bin\" -c \"isolinux/boot.cat\" -no-emul-boot -boot-load-size 4 -boot-info-table -V \"' + self.isoName + '\" -cache-inodes -r -J -l \"' + self.bootPath + '\"')

                print("Making Hybrid ISO...")
                self.ec.run("isohybrid %s" % self.isoFileName)

                print("Create ISO md5 file...")
                self.ec.run("echo \"$(md5sum \"%s\" | cut -d' ' -f 1)  %s\" > \"%s.md5\"" % (self.isoFileName, self.isoBaseName, self.isoFileName))

                print("Create Torrent file...")
                torrentFile = "%s.torrent" % self.isoFileName
                if exists(torrentFile):
                    remove(torrentFile)
                self.ec.run("mktorrent -a \"%s\" -c \"%s\" -w \"%s\" -o \"%s\" \"%s\"" % (self.trackers, self.isoName, self.webseeds, torrentFile, self.isoFileName))

                print("======================================================")
                self.returnMessage = "DONE - ISO Located at: %s" % self.isoFileName
                print((self.returnMessage))
                print("======================================================")

            self.queue.put(self.returnMessage)

        except Exception as detail:
            self.returnMessage = "ERROR: BuildIso: %(detail)s" % {"detail": detail}
            self.queue.put(self.returnMessage)

    def copy_file(self, file_path, destination):
        if exists(file_path):
            try:
                copy(file_path, destination)
            except Exception as detail:
                print(("ERROR: BuildIso.copy_file: {}".format(detail)))
        else:
            print(("ERROR: BuildIso.copy_file: cannot find {}".format(file_path)))


# Class to create a chrooted terminal for a given directory
# https://wiki.debian.org/chroot
class EditDistro(object):

    def __init__(self, distroPath):
        self.ec = ExecCmd()
        self.dg = DistroGeneral(distroPath)
        distroPath = distroPath.rstrip('/')
        if basename(distroPath) == "root":
            distroPath = dirname(distroPath)
        self.rootPath = join(distroPath, "root")

        # ISO edition
        self.edition = self.dg.edition

    def openTerminal(self, command=""):
        # Set some paths
        resolveCnfHost = "/etc/resolv.conf"
        resolveCnf = join(self.rootPath, "etc/resolv.conf")
        resolveCnfBak = "%s.bak" % resolveCnf
        wgetrc = join(self.rootPath, "etc/wgetrc")
        wgetrcBak = "%s.bak" % wgetrc
        terminal = "/tmp/constructor-terminal.sh"
        lockDir = join(self.rootPath, "run/lock/")
        proc = join(self.rootPath, "proc/")
        dev = join(self.rootPath, "dev/")
        pts = join(self.rootPath, "dev/pts/")
        sys = join(self.rootPath, "sys/")
        policy = join(self.rootPath, "usr/sbin/policy-rc.d")
        ischroot = join(self.rootPath, "usr/bin/ischroot")
        ischrootTmp = join(self.rootPath, "usr/bin/ischroot.tmp")

        try:
            # temporary create /run/lock
            if not exists(lockDir):
                makedirs(lockDir)

            # setup environment
            # copy dns info
            if exists(resolveCnf):
                move(resolveCnf, resolveCnfBak)
            if exists(resolveCnfHost):
                copy(resolveCnfHost, resolveCnf)

            # umount /proc /dev /dev/pts /sys
            self.unmount([pts, dev, proc, sys])

            # mount /proc /dev /dev/pts /sys /run /sys
            self.ec.run("mount --bind /proc '%s'" % proc)
            self.ec.run("mount --bind /dev '%s'" % dev)
            self.ec.run("mount --bind /dev/pts '%s'" % pts)
            self.ec.run("mount --bind /sys '%s'" % sys)

            # copy apt.conf
            #copy("/etc/apt/apt.conf", join(self.rootPath, "etc/apt/apt.conf"))

            # copy wgetrc
            move(wgetrc, wgetrcBak)
            copy("/etc/wgetrc", wgetrc)

            # Let dpkg only start daemons when desired
            scr = "#!/bin/sh\nexit 101\n"
            with open(policy, 'w') as f:
                f.write(scr)
            self.ec.run("chmod a+x %s" % policy)

            # Temporary fix ischroot
            if not exists(ischrootTmp):
                self.ec.run("mv %s %s" % (ischroot, ischrootTmp))
            if not exists(ischroot):
                self.ec.run("ln -s /bin/true %s" % ischroot)

            # HACK: create temporary script for chrooting
            if exists(terminal):
                remove(terminal)
            scr = "#!/bin/sh\nchroot '%s' %s\n" % (self.rootPath, command)
            with open(terminal, 'w') as f:
                f.write(scr)
            self.ec.run("chmod a+x %s" % terminal)
            if self.ec.run('which x-terminal-emulator'):
                # use x-terminal-emulator if xterm isn't available
                if exists("/usr/bin/xterm"):
                    self.ec.run('export HOME=/root ; xterm -bg black -fg white -rightbar -title \"%s\" -e %s' % (self.edition, terminal))
                else:
                    self.ec.run('export HOME=/root ; x-terminal-emulator -e %s' % terminal)
            else:
                print('Error: no valid terminal found')

            # restore wgetrc
            move(wgetrcBak, wgetrc)

            # remove apt.conf
            #remove(join(self.rootPath, "root/etc/apt/apt.conf"))

            # move dns info
            if exists(resolveCnfBak):
                move(resolveCnfBak, resolveCnf)
            else:
                remove(resolveCnf)

            # umount /proc /dev /dev/pts /sys
            self.unmount([pts, dev, proc, sys])

            # remove temp script
            if exists(terminal):
                remove(terminal)

            # remove policy script
            if exists(policy):
                remove(policy)

            # replace ischroot
            if exists("%s.tmp" % ischroot):
                self.ec.run("rm %s" % ischroot)
                self.ec.run("mv %s.tmp %s" % (ischroot, ischroot))

            # cleanup /run
            self.ec.run("rm -rf %s/run/*" % self.rootPath)

        except Exception as detail:
            # restore wgetrc
            move(wgetrcBak, wgetrc)

            # remove apt.conf
            #remove(join(self.rootPath, "etc/apt/apt.conf"))

            # move dns info
            if exists(resolveCnfBak):
                move(resolveCnfBak, resolveCnf)
            else:
                remove(resolveCnf)

            # umount /proc /dev /dev/pts /sys
            self.unmount([pts, dev, proc, sys])

            # remove temp script
            if exists(terminal):
                remove(terminal)

            # remove policy script
            if exists(policy):
                remove(policy)

            # replace ischroot
            if exists("%s.tmp" % ischroot):
                self.ec.run("rm %s" % ischroot)
                self.ec.run("mv %s.tmp %s" % (ischroot, ischroot))

            # cleanup /run
            self.ec.run("rm -rf %s/run/*" % self.rootPath)

            errText = 'Error launching terminal: '
            print((errText, detail))

    def unmount(self, mounts=[]):
        for mount in mounts:
            self.ec.run("umount --force '%s'" % mount)
            self.ec.run("umount -l '%s'" % mount)


class DistroGeneral(object):

    def __init__(self, distroPath):
        self.ec = ExecCmd()
        distroPath = distroPath.rstrip('/')
        if basename(distroPath) == "root":
            distroPath = dirname(distroPath)
        self.distroPath = distroPath
        self.rootPath = join(distroPath, "root")

        self.edition = basename(distroPath)
        self.description = "SolydXK"
        infoPath = join(self.rootPath, "etc/solydxk/info")
        if exists(infoPath):
            self.edition = self.ec.run(cmd="grep EDITION= {} | cut -d'=' -f 2".format(infoPath), returnAsList=False).strip('"')
            self.description = self.ec.run(cmd="grep DESCRIPTION= {} | cut -d'=' -f 2".format(infoPath), returnAsList=False).strip('"')

    def getPlymouthTheme(self):
        plymouthTheme = ""
        if exists(join(self.rootPath, "usr/share/plymouth/themes/solydk-logo")):
            plymouthTheme = "solydk-logo"
        elif exists(join(self.rootPath, "usr/share/plymouth/themes/solydx-logo")):
            plymouthTheme = "solydx-logo"
        return plymouthTheme

    def getIsoFileName(self):
        # Get the date string
        d = datetime.now()
        serial = d.strftime("%Y%m")
        # Check for a localized system
        localePath = join(self.rootPath, "etc/default/locale")
        if exists(localePath):
            locale = self.ec.run(cmd="grep LANG= {}".format(localePath), returnAsList=False).strip('"').replace(" ", "")
            matchObj = re.search("\=\s*([a-z]{2})", locale)
            if matchObj:
                language = matchObj.group(1)
                if language != "en":
                    serial += "_{}".format(language)
        isoFileName = "{}_{}.iso".format(self.description.lower().replace(' ', '_').split('-')[0], serial)
        return isoFileName
