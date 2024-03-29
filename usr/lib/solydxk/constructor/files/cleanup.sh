#!/bin/bash

# Packages that deborphan must NOT treat as orphans - comma separated list
NotOrphan='baloo'

function sed_append_sting {
  PATTERN=$1
  LINE=$2
  FLE=$3
  
  if [ -e $FLE ]; then
    if grep -q $PATTERN "$FLE"; then
      # Escape forward slashes
      LINE=$(echo $LINE | sed 's/\//\\\//g')
      sed -i -e "s/$PATTERN/$LINE/" $FLE
    else
      echo $LINE >> $FLE
    fi
  fi
}

PLYMOUTHTHEME=$1

# Remove fake mime types in kde
if [ -e /usr/share/mime/packages/kde.xml ]; then
  sed -i -e /\<.*fake.*\>/,/^$/d /usr/share/mime/packages/kde.xml
fi

# Write the current up version
if [ -e '/usr/lib/solydxk/updatemanager/files' ]; then
  wget http://repository.solydxk.com/umfiles/repo.info
  if [ -e 'repo.info' ]; then
    VER=$(cat 'repo.info' | grep 'upd=')
    echo $VER > /usr/lib/solydxk/updatemanager/files/updatemanager.hist
    rm 'repo.info'
  fi
fi

# Make sure all firmware drivers are installed
sudo apt-get -y --force-yes install $(aptitude search ^firmware | grep ^p | awk '{print $2}')

# Cleanup
apt-get -y --force-yes clean
apt-get -y --force-yes autoremove
aptitude -y purge ~c
aptitude -y unmarkauto ~M
find . -type f -name "*.dpkg*" -exec rm {} \;

# Remove unavailable packages only when not manually held back
for PCK in $(env LANG=C bash -c "apt-show-versions | grep 'available' | cut -d':' -f1"); do
  REMOVE=true
  for HELDPCK in $(env LANG=C dpkg --get-selections | grep hold$ | awk '{print $1}'); do
    if [ $PCK == $HELDPCK ]; then
      REMOVE=false
    fi
  done
  if $REMOVE; then
    apt-get purge -y --force-yes $PCK
  fi
done

# Removing orphaned packages, except the ones listed in NotOrphan
echo "Removing orphaned packages . . ."
Exclude=${NotOrphan//,/\/d;/}
Orphaned=$(deborphan | sed '/'$Exclude'/d')
while [ "$Orphaned" ]; do
   apt-get -y --force-yes purge $Orphaned
   RC=$(dpkg-query -l | sed -n 's/^rc\s*\(\S*\).*/\1/p')
   [ "$RC" ] && apt-get -y --force-yes purge $RC
   Orphaned=$(deborphan | sed '/'$Exclude':/d')
done

# Disable memtest in Grub
chmod -x /etc/grub.d/20_memtest86+

# Set plymouth theme
if [ "$PLYMOUTHTHEME" != "" ]; then
  plymouth-set-default-theme -R $PLYMOUTHTHEME
  echo "Plymouth theme set: $(plymouth-set-default-theme)"
  update-grub
fi

# Configure LightDM
CONF='/etc/lightdm/lightdm-kde-greeter.conf'
if [ -e '/etc/lightdm/lightdm-gtk-greeter.conf' ]; then
  CONF='/etc/lightdm/lightdm-gtk-greeter.conf'
fi
   
if [ -e /usr/bin/startxfce* ]; then
  sed_append_sting '^background\s*=.*' 'background=/usr/share/images/desktop-base/solydx-lightdmbg.png' $CONF
  sed_append_sting '^theme-name\s*=.*' 'theme-name=greybird-solydx' $CONF
elif [ -e /usr/bin/startkde* ]; then
  sed_append_sting '^background\s*=.*' 'background=/usr/share/images/desktop-base/solydk-lightdmbg.png' $CONF
  sed_append_sting '^theme-name\s*=.*' 'theme-name=greybird-solydk-gtk3' $CONF
else
  sed_append_sting '^background\s*=.*' 'background=' $CONF
  sed_append_sting '^theme-name\s*=.*' 'theme-name=' $CONF
fi
sed_append_sting '^default-user-image\s*=.*' 'default-user-image=/usr/share/pixmaps/faces/user-generic.png' $CONF
    
CONF='/etc/lightdm/lightdm.conf'
if [ -e $CONF ]; then
  sed -i -e '/^greeter-hide-users\s*=/ c greeter-hide-users=false' $CONF
  sed -i -r 's/^#?(autologin-user)\s*=.*/\1=solydxk/' $CONF
  sed -i -r 's/^#?(autologin-user-timeout)\s*=.*/\1=0/' $CONF
fi

# Set default SolydXK settings
/usr/lib/solydxk/system/adjust.py

# Refresh xapian database
update-apt-xapian-index

# Update database for mlocate
updatedb

# Update geoip database
if [ -e /usr/sbin/update-geoip-database ]; then
  /usr/sbin/update-geoip-database
fi

# Recreate pixbuf cache
PB='/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders'
if [ -e $PB ]; then
  $PB --update-cache
else
  PB='/usr/lib/i386-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders'
  if [ -e $PB ]; then
    $PB --update-cache
  fi
fi

# Settings for the firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow CIFS
ufw enable

# Cleanup temporary files
rm -rf /media/*
rm -rf /var/backups/*
rm -rf /tmp/*
rm -rf /tmp/.??*
rm -rf /var/tmp/*
rm -rf /var/tmp/.??*
if [ -d /offline ]; then
  rm -rf /offline
fi

# Delete all log files
find /var/log -type f -delete

# Delete grub.cfg: it will be generated during install
rm -rf /boot/grub/grub.cfg

# Removing redundant kernel module structure(s) from /lib/modules (if any)
VersionPlusArch=$(ls -l /vmlinuz | sed 's/.*\/vmlinuz-\(.*\)/\1/')
L=${#VersionPlusArch}
for I in /lib/modules/*; do
   if [ ${I: -$L} != $VersionPlusArch ] && [ ! -d $I/kernel ]; then
      echo "Removing redundant kernel module structure: $I"
      rm -fr $I
   fi
done
