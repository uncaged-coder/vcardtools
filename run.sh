#!/bin/bash

# run.sh - A script for managing, normalizing, importing, and exporting contacts in vCard format.
#
# USAGE:
# ./run.sh <command> [optional address book]
#
# COMMANDS:
# -e    Export a specific address book or all address books to a single VCF file.
# -i    Import a VCF from the specified address book, merge it with the existing contact files, and remove duplicates.
#
# EXAMPLES:
# ./run.sh -e friends          # Export the 'friends' address book to a group VCF.
# ./run.sh -i family           # Import the 'family' address book, merge and normalize contacts.
#
# CONFIGURATION:
# The script expects a configuration file located at ~/.config/vcardtools/config.ini.
# If the configuration file or any required values are missing, the script will terminate with an error message.
#
# Sample config.ini:
#
# [DEFAULT]
# work_dir = /tmp/vcardtools_out
# contact_dir = /zdata/progs/perso/contacts
# addr_books = family bled friends xx yy net_friends old_colleagues old_friends school services zzz
#
# Make sure all the config parameters are present, as they are mandatory.

set -e

CONFIG_FILE="$HOME/.config/vcardtools/config.ini"

# Function to read values from the config file and ensure they are provided
get_config_value() {
  section=$1
  key=$2
  value=$(awk -F '=' '/\['"$section"'\]/{a=1} a==1&&$1~/'"$key"'/{print $2;exit}' $CONFIG_FILE)

  if [ -z "$value" ]; then
    echo "Error: Missing required configuration for '$key' in section '$section'."
    exit 1
  fi
  echo "$value"
}

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
  echo "Error: Config file not found at $CONFIG_FILE"
  exit 1
fi

# Load config values
WORK_DIR=$(get_config_value "DEFAULT" "work_dir")
CONTACT_DIR=$(get_config_value "DEFAULT" "contact_dir")
ADDR_BOOKS=$(get_config_value "DEFAULT" "addr_books")
OUT_DIR="${WORK_DIR}/out"
MERGE_ATTR="--match-attributes email --match-attributes names --match-attributes tel"
VCARDTOOLS_OPTIONS="-e .vcf --no-space-in-filename"

# Define pushd and popd without stdout output
pushd() {
  command pushd "$@" >/dev/null
}

popd() {
  command popd "$@" >/dev/null
}

import_contacts() {
  ADDR_BOOK=$1
  CURRENT_MERGED_VCF=${WORK_DIR}/in_current.vcf
  CURRENT_VCF_FILES_DIR=${CONTACT_DIR}/${ADDR_BOOK}
  IMPORTED_MERGED_VCF=${CONTACT_DIR}/xfer_android/imported_${ADDR_BOOK}.vcf

  if ! [ -f ${IMPORTED_MERGED_VCF} ]; then
    echo "No imported contact for $ADDR_BOOK}"
    return
  fi

  # Remove current merged VCF file (if exists)
  rm -f ${CURRENT_MERGED_VCF}

  # Merge current VCF files and imported VCF
  cat ${CURRENT_VCF_FILES_DIR}/*.vcf >>${CURRENT_MERGED_VCF}
  python3 vcardtools.py ${VCARDTOOLS_OPTIONS} --merge ${MERGE_ATTR} ${OUT_DIR} ${CURRENT_MERGED_VCF} ${IMPORTED_MERGED_VCF}

  dos2unix ${OUT_DIR}/*.vcf

  # Insert CATEGORY
  pushd ${OUT_DIR}
  sed -i '/^X-GROUP-MEMBERSHIP:.*/a CATEGORIES:'${ADDR_BOOK} *.vcf
  popd

  # Remove duplicate lines
  pushd ${OUT_DIR}
  for f in *.vcf; do gawk -i inplace '!seen[$0]++' "$f"; done
  popd

  # Git operations
  pushd ${CURRENT_VCF_FILES_DIR}
  git rm *.vcf
  popd
  mv ${OUT_DIR}/*.vcf ${CURRENT_VCF_FILES_DIR}
  rmdir ${OUT_DIR}

  pushd ${CURRENT_VCF_FILES_DIR}
  git add *.vcf
  git commit -s -m "autocommit vcardtools import for ${ADDR_BOOK} from $(hostname)" || {
    echo "Git commit failed!"
    exit 1
  }
  popd
}

export_contacts() {
  ADDR_BOOK=$1
  CURRENT_VCF_FILES_DIR=${CONTACT_DIR}/${ADDR_BOOK}
  EXPORTED_VCF=${CONTACT_DIR}/xfer_android/exported_${ADDR_BOOK}.vcf

  pushd ${CURRENT_VCF_FILES_DIR}
  cat *.vcf >${EXPORTED_VCF}
  git add -A
  git commit -s -m "autocommit vcardtools export for ${ADDR_BOOK} from $(hostname)" || {
    echo "Git commit failed!"
    exit 1
  }
  popd

  echo "Exported ${ADDR_BOOK}"
}

# Show usage if no arguments are provided
if [ $# -lt 1 ]; then
  echo "Usage: $0 command [optional addr book]"
  exit 0
fi

COMMAND=$1

# If a second argument is passed, override addr books with that value
if [ $# -eq 2 ]; then
  ADDR_BOOKS=$2
fi

# Handle commands
if [ "$COMMAND" == "-i" ]; then
  for f in $ADDR_BOOKS; do
    import_contacts $f
  done
  exit 0
fi

if [ "$COMMAND" == "-e" ]; then
  for f in $ADDR_BOOKS; do
    export_contacts $f
  done
fi
