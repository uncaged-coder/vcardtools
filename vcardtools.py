#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Command line tool to fix, convert, split, normalize, group, merge, deduplicate
vCard and VCF files from version 2.1 to 3.0 (even large ones)."""

import argparse
import logging
import re
from sys import stderr, exit as sysexit
from os import makedirs
from os.path import exists, isfile, split as pathsplit
from unidecode import unidecode
import vcardlib
from vcardlib import (
    get_vcards_from_files,
    get_vcards_groups,
    collect_attributes,
    set_name,
    build_vcard,
    write_vcard_to_file)

DEFAULT_VCARD_EXTENSION = '.vcard'
OPTION_NO_SPACE_IN_FILENAME = False
OPTION_FORCE_LOWER_CASE_IN_FILENAME = False
OPTION_REPLACE_INVALID_FILENAME_CHAR_BY = '_'

def init_parser():
    """Setup the CLI argument parser with the definition of arguments and options."""
    parser = argparse.ArgumentParser(
        description="Automatically fix / convert / split / normalize / group / merge / deduplicate "
                    "vCard and VCF files from version 2.1 to 3.0 (even large ones)."
    )
    parser.add_argument(
        'dest_dir', metavar='DESTDIR',
        help="The directory that will contains VCF (vCard) files merged. "
             "It MUST not exists already."
    )
    parser.add_argument(
        'files', metavar='FILES', nargs='+',
        help='The vcf/vcard files that contains vCards.'
    )
    parser.add_argument(
        '-e', '--vcard-extension', dest='vcard_extension', type=str, default=DEFAULT_VCARD_EXTENSION,
        help="The extension to use for vcard files. Default is: {dve}.".format(dve=DEFAULT_VCARD_EXTENSION)
    )
    parser.add_argument(
        '-g', '--group', dest='group_vcards', action='store_true',
        help="Group vcards that match into a directory."
    )
    parser.add_argument(
        '-m', '--merge', dest='merge_vcards', action='store_true',
        help="Merge vcards that match into a single file."
    )
    parser.add_argument(
        '-x', '--no-match-approx', dest='no_match_approx', action='store_true',
        help="Disable using approximate matching on names (note: names/words order will count)."
    )
    parser.add_argument(
        '-c', '--no-fix-and-convert', dest='no_fix_and_convert', action='store_true',
        help="Disable fixing invalid lines, and broken multilines value, "
             "and converting from vCard 2.1 to 3.0"
    )
    parser.add_argument(
        '-n', '--no-overwrite-names', dest='no_overwrite_names', action='store_true',
        help="Do not overwrite names in the vCard, i.e.: keep 'fn' and 'n' attributes untouched"
    )
    parser.add_argument(
        '-f', '--french-tweaks', dest='french_tweaks', action='store_true',
        help="Enable french tweaks (phone number '+33' converted to '0', "
             "handling of the name particule ' De ')."
    )
    parser.add_argument(
        '-a', '--match-attributes', dest='match_attributes', action='append',
        default=vcardlib.OPTION_MATCH_ATTRIBUTES,
        help="Use those attributes to match vCards. Two vCards matches when at least one of those "
             "attributes match. Specials attributes: 'names' is an alias for 'fn'+'n' and "
             "'mobiles' for 'tel'+filter by phone number. Default is: %s. Use the argument "
             "multiple times to specify multiple values." % vcardlib.OPTION_MATCH_ATTRIBUTES
    )
    parser.add_argument(
        '-t', '--match-ratio', dest='match_ratio', type=int, default=100,
        help="The ratio score to match the names (see fuzzywuzzy documentation). "
             "Default is: 100 (safe)."
    )
    parser.add_argument(
        '-i', '--match-min-length', dest='match_min_length', type=int, default=5,
        help="The minimum length of string to allow an approximate match. Default is: 5."
    )
    parser.add_argument(
        '-d', '--match-max-distance', dest='match_max_distance', type=int, default=3,
        help="The number of character between to length of names that matches. Default is: 3."
    )
    parser.add_argument(
        '-1', '--no-match-same-first-letter', dest='no_match_same_first_letter',
        action='store_true',
        help="Do not ensure that name's first letter match when doing approximate matching"
    )
    parser.add_argument(
        '-s', '--match-startswith', dest='match_startswith', action='store_true',
        help="Use the startswith comparizon (using --match-max-distance) "
             "when doing approximate matching"
    )
    parser.add_argument(
        '--move-name-extra-info-to-note', dest='move_name_parentheses_or_braces_to_note',
        action='store_true',
        help="Move name's charaecters between parentheses or braces to note attribute"
    )
    parser.add_argument(
        '--no-remove-name-in-email', dest='no_remove_name_in_email', action='store_true',
        help="Do not removes name in email, i.e.: keep email like the following untouched: "
             "\"John Doe\" <john@doe.com>"
    )
    parser.add_argument(
        '--do-not-force-escape-commas', dest='do_not_force_escape_commas', action='store_true',
        help="Disable automatically escaping commas."
    )
    parser.add_argument(
        '--no-space-in-filename', dest='no_space_in_filename', action='store_true',
        help="Replace space in generated filename by '" +
             OPTION_REPLACE_INVALID_FILENAME_CHAR_BY + "' (or option --rep-invalid-fn-char-by)."
    )
    parser.add_argument(
        '--force-lower-case-in-filename', dest='force_lower_case_in_filename', action='store_true',
        help="Replace upper case into lower case in generated filename"
    )
    parser.add_argument(
        '--rep-invalid-fn-char-by', dest='rep_invalid_fn_char_by', type=str,
        default=OPTION_REPLACE_INVALID_FILENAME_CHAR_BY,
        help="Replace invalid characters in filename by the specified character. Default to '" +
             OPTION_REPLACE_INVALID_FILENAME_CHAR_BY + "'"
    )
    parser.add_argument(
        '-l', '--log-level', dest='log_level', default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help="the logging level in (DEBUG,INFO,WARNING,ERROR), default is: INFO"
    )
    return parser

def sanitise_name(a_name: str) -> str:
    """
    Sanitises a filename by converting it to lowercase, removing accents, and replacing invalid characters.
    Allows or disallows spaces based on the 'OPTION_NO_SPACE_IN_FILENAME' option.

    Args:
    - a_name: The original filename to be sanitised.

    Returns:
    - The sanitised filename.
    """
    # Convert to ASCII and remove accents
    sanitised = unidecode(a_name)

    if OPTION_FORCE_LOWER_CASE_IN_FILENAME:
        sanitised = sanitised.lower()

    # Define characters that are invalid in filenames
    invalid_characters = r'.\\/"\'!@#?$%^&*|(){};:<>[]'
    if OPTION_NO_SPACE_IN_FILENAME:
        invalid_characters = ' ' + invalid_characters

    # Replace all invalid characters with the specified replacement character
    sanitised = re.sub(f'[{re.escape(invalid_characters)}]+', OPTION_REPLACE_INVALID_FILENAME_CHAR_BY, sanitised)

    # Replace multiple consecutive replacement characters with a single one
    return re.sub(f'{re.escape(OPTION_REPLACE_INVALID_FILENAME_CHAR_BY)}+', OPTION_REPLACE_INVALID_FILENAME_CHAR_BY, sanitised)

def generate_vcard_filename(a_name: str = '', ext: str = '') -> str:
    """ Make a vcard filename, by first sanitising the filename
        and then adding the defined extension.
    """
    return sanitise_name(a_name=a_name) + ext

def generate_group_dirname(a_name: str = '') -> str:
    """ Return a group name, sanitised
    """
    return sanitise_name(a_name=a_name)

def main():  # pylint: disable=too-many-statements,too-many-branches
    """Main program : running the command line."""
    global OPTION_NO_SPACE_IN_FILENAME, OPTION_REPLACE_INVALID_FILENAME_CHAR_BY, OPTION_FORCE_LOWER_CASE_IN_FILENAME

    try:  # pylint: disable=too-many-nested-blocks
        parser = init_parser()
        args = parser.parse_args()

        # set the log level and log format accordingly
        log_format = '%(levelname)-8s %(message)s'
        if args.log_level == 'DEBUG':
            logging.basicConfig(level=logging.DEBUG, format=log_format)
        elif args.log_level == 'INFO':
            logging.basicConfig(level=logging.INFO, format=log_format)
        elif args.log_level == 'WARNING':
            logging.basicConfig(level=logging.WARNING, format=log_format)
        elif args.log_level == 'ERROR':
            logging.basicConfig(level=logging.ERROR, format=log_format)
        else:
            stderr.write("[ERROR] Invalid log level '" + args.log_level + "'\n\n")
            parser.print_help()
            sysexit(2)

        # Set the extension to use when saving vcard files
        the_vcard_ext = args.vcard_extension

        # no match approx
        vcardlib.OPTION_NO_MATCH_APPROX = args.no_match_approx

        # match attributes
        if args.match_attributes and isinstance(args.match_attributes, list):
            if args.match_attributes != vcardlib.OPTION_MATCH_ATTRIBUTES:
                vcardlib.OPTION_MATCH_ATTRIBUTES = (
                    args.match_attributes[len(vcardlib.OPTION_MATCH_ATTRIBUTES):])

        # match approx min length
        if args.match_min_length and isinstance(args.match_min_length, int):
            vcardlib.OPTION_MATCH_APPROX_MIN_LENGTH = args.match_min_length

        # match approx same first letter
        vcardlib.OPTION_MATCH_APPROX_SAME_FIRST_LETTER = not args.no_match_same_first_letter

        # match approx startswith
        vcardlib.OPTION_MATCH_APPROX_STARTSWITH = args.match_startswith

        # match approx max distance
        if args.match_max_distance and isinstance(args.match_max_distance, int):
            vcardlib.OPTION_MATCH_APPROX_MAX_DISTANCE = range(
                -args.match_max_distance, args.match_max_distance)

        # match ratio
        if args.match_ratio and isinstance(args.match_ratio, int):
            vcardlib.OPTION_MATCH_APPROX_RATIO = args.match_ratio

        # french tweaks
        vcardlib.OPTION_FRENCH_TWEAKS = args.french_tweaks

        # comma auto escape
        vcardlib.OPTION_DO_NOT_FORCE_ESCAPE_COMMAS = args.do_not_force_escape_commas

        # no space in filename
        OPTION_NO_SPACE_IN_FILENAME = args.no_space_in_filename

        OPTION_FORCE_LOWER_CASE_IN_FILENAME = args.force_lower_case_in_filename

        # replacement of invalid chars in filename
        OPTION_REPLACE_INVALID_FILENAME_CHAR_BY = args.rep_invalid_fn_char_by


        # check DESTDIR argument
        if exists(args.dest_dir):
            stderr.write("[ERROR] Directory '" + args.dest_dir + "' exists. "
                         "Do not want to overwrite something\n\n")
            parser.print_help()
            sysexit(2)
        # create DIR
        else:
            # Make sure args.dest_dir has not ending '/' before adding a new '/' in other steps
            dirname, subdir = pathsplit(args.dest_dir)
            if (subdir == ''):
                args.dest_dir = dirname
            makedirs(args.dest_dir)
            logging.info("Created directory '%s'", args.dest_dir)

        # check FILES argument
        for arg_file in args.files:
            if not exists(arg_file):
                stderr.write("[ERROR] File '" + arg_file + "' doesn't exist\n\n")
                parser.print_help()
                sysexit(2)
            elif not isfile(arg_file):
                stderr.write("[ERROR] '" + arg_file + "' is not a regular file\n\n")
                parser.print_help()
                sysexit(2)

        # summary of options
        logging.info("Options:")
        logging.info("\tMATCH_ATTRIBUTES: %s", vcardlib.OPTION_MATCH_ATTRIBUTES)
        logging.info("\tNO_MATCH_APPROX: %s", vcardlib.OPTION_NO_MATCH_APPROX)
        if not vcardlib.OPTION_NO_MATCH_APPROX:
            logging.info("\tMATCH_APPROX_SAME_FIRST_LETTER: %s",
                         vcardlib.OPTION_MATCH_APPROX_SAME_FIRST_LETTER)
            logging.info("\tMATCH_APPROX_STARTSWITH: %s", vcardlib.OPTION_MATCH_APPROX_STARTSWITH)
            logging.info("\tMATCH_APPROX_MIN_LENGTH: %s", vcardlib.OPTION_MATCH_APPROX_MIN_LENGTH)
            logging.info("\tMATCH_APPROX_MAX_DISTANCE: %s",
                         vcardlib.OPTION_MATCH_APPROX_MAX_DISTANCE)
            logging.info("\tMATCH_APPROX_RATIO: %s", vcardlib.OPTION_MATCH_APPROX_RATIO)
        logging.info("\tFRENCH_TWEAKS: %s", vcardlib.OPTION_FRENCH_TWEAKS)

        # read/parse individual vCard files
        vcards = get_vcards_from_files( \
                args.files, \
                args.no_fix_and_convert, \
                args.no_overwrite_names, \
                args.move_name_parentheses_or_braces_to_note, \
                args.no_remove_name_in_email \
        )

        # group vcards
        if args.group_vcards or args.merge_vcards:
            vcards_grouped, vcards_not_grouped = get_vcards_groups(vcards)

            # create grouped vCard files in group dirs
            logging.info("Processing '%d' grouped vCard ...", len(vcards_grouped))
            for g_name, g_list in sorted(vcards_grouped.items()):
                if len(g_list) > 1:
                    logging.debug("\t%s (%d vcards)", g_name, len(g_list))
                    d_path = args.dest_dir + "/" + generate_group_dirname(g_name)

                    # merge
                    if args.merge_vcards:
                        # collect vcards to merge
                        vcards_to_merge = []
                        for key in g_list:
                            vcards_to_merge.append(vcards[key])
                        # collect attributes for all vCards
                        attributes = collect_attributes(vcards_to_merge)
                        # select a name
                        set_name(attributes)
                        # save the remaining attributes to the merged vCard
                        vcard_merge = build_vcard(attributes)
                        # write to the file
                        write_vcard_to_file(vcard_merge, d_path + the_vcard_ext)

                    # group
                    else:
                        makedirs(d_path)
                        logging.debug("\t%s", d_path)
                        for key in g_list:
                            logging.debug("\t\t%s", key)
                            write_vcard_to_file(
                                vcards[key],
                                d_path + '/' + generate_vcard_filename(key, the_vcard_ext))
                else: # should not happen
                    raise RuntimeError("Only one vcard in group '" + g_name + "' "
                                       "(should not happen)")

            # create vCard files not grouped in dest dir root
            if vcards_not_grouped:
                logging.info("Creating '%d' not grouped vCard files (in root dir) ...",
                             len(vcards_not_grouped))
                for key in vcards_not_grouped:
                    write_vcard_to_file(
                        vcards[key],
                        args.dest_dir + '/' + generate_vcard_filename(key, the_vcard_ext))

        # no grouping
        elif vcards:

            # create vCard files not grouped in dest dir root
            logging.info("Creating '%d' not grouped vCard files (in root dir) ...", len(vcards))
            for key, vcard in vcards.items():
                write_vcard_to_file(vcard, args.dest_dir + '/' + generate_vcard_filename(key, the_vcard_ext))


    # user CTRL-C
    except KeyboardInterrupt:
        logging.info("\nUser interupted. Bye.")
        sysexit(3)


if __name__ == "__main__":
    main()
