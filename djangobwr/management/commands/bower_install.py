import os
import sys
import json
import tempfile
import shutil
import hashlib
import glob
from subprocess import call, check_output, CalledProcessError
from optparse import make_option

from django.core.management.base import BaseCommand
from django.conf import settings

from djangobwr.finders import AppDirectoriesFinderBower


class Command(BaseCommand):
    """Command goes through apps. If description files are in the app,
    it will install it in a temporary folder:

        - package.json: npm install
        - Gruntfile.js: grunt default
        - bower.json: bower install
    """
    option_list = BaseCommand.option_list + (
        make_option('--with-version', dest='with_version', default=False, action='store_true',
            help='Create component directories with version numbers'),
    )
    bower_info = {}

    def npm_install(self, pkg_json_path):
        os.chdir(os.path.dirname(pkg_json_path))
        call(['npm', 'install'])

    def grunt_default(self, grunt_js_path):
        os.chdir(os.path.dirname(grunt_js_path))
        call(['grunt'])

    def bower_install(self, bower_json_path, dest_dir):
        """Runs bower commnand for the passed bower.json path.

        :param bower_json_path: bower.json file to install
        :param dest_dir: where the compiled result will arrive
        """

        # Verify that we are able to run bower, in order to give a good error message in the
        # case that it's not installed.  Do this separately from the 'bower install' call, in
        # order not to warn about a missing bower in the case of installation-related errors.
        try:
            bower_version = check_output(['bower', '--version'])
        except OSError as e:
            print("Trying to run bower failed -- is it installed?  The error was: %s" % e)
            exit(1)
        except CalledProcessError as e:
            print("Checking the bower version failed: %s" % e)
            exit(2)
        print("Bower %s" % bower_version)

        # bower args
        args = ['bower', 'install', bower_json_path,
                '--verbose', '--config.cwd={}'.format(dest_dir), '-p']

        # run bower command
        call(args)

    def get_bower_info(self, bower_json_path):
        if not bower_json_path in self.bower_info:
            self.bower_info[bower_json_path] = json.load(open(bower_json_path))

    def get_bower_main_list(self, bower_json_path):
        """Returns the bower.json main list or empty list.
        """
        self.get_bower_info(bower_json_path)

        main_list = self.bower_info[bower_json_path].get('main')

        if isinstance(main_list, list):
            return main_list

        if main_list:
            return [main_list]

        return []

    def get_bower_version(self, bower_json_path):
        """Returns the bower.json main list or empty list.
        """
        self.get_bower_info(bower_json_path)

        return self.bower_info[bower_json_path].get("version")

    def clean_components_to_static_dir(self, bower_dir):

        component_root = getattr(settings, 'COMPONENT_ROOT', os.path.join(settings.STATIC_ROOT, "components"))

        for directory in os.listdir(bower_dir):
            print("Component: %s" % (directory, ))

            src_root = os.path.join(bower_dir, directory)

            for bower_json in ['bower.json', '.bower.json']:
                bower_json_path = os.path.join(src_root, bower_json)
                if os.path.exists(bower_json_path):
                    main_list = self.get_bower_main_list(bower_json_path)
                    version   = self.get_bower_version(bower_json_path)

                    dst_root = os.path.join(component_root, directory)
                    if self.with_version:
                        assert not dst_root.endswith(os.sep)
                        dst_root += "-"+version

                    for pattern in filter(None, main_list):
                        src_pattern = os.path.join(src_root, pattern)
                        # main_list elements can be fileglob patterns
                        for src_path in glob.glob(src_pattern):
                            # See if we have a minified alternative
                            path, ext = os.path.splitext(src_path)
                            min_path = path+".min"+ext
                            if os.path.exists(min_path):
                                src_path = min_path

                            if not os.path.exists(src_path):
                                print("Could not find source path: %s" % (src_path, ))

                            # Build the destination path
                            base = os.path.basename(src_path)
                            dst_path = os.path.join(dst_root, base)

                            # Normalize the paths, for good looks
                            src_path = os.path.abspath(src_path)
                            dst_path = os.path.abspath(dst_path)

                            # Check if we need to copy the file at all.
                            if os.path.exists(dst_path):
                                with open(src_path) as src:
                                    src_hash = hashlib.sha1(src.read()).hexdigest()
                                with open(dst_path) as dst:
                                    dst_hash = hashlib.sha1(dst.read()).hexdigest()
                                if src_hash == dst_hash:
                                    #print('{0} = {1}'.format(src_path, dst_path))
                                    continue

                            # Make sure dest dir exists.
                            if not os.path.exists(dst_root):
                                os.makedirs(dst_root)

                            print('  {0} > {1}{2}'.format(src_path, dst_root, os.sep))
                            shutil.copy(src_path, dst_root)
                    break

    def handle(self, *args, **options):

        self.with_version = options.get("with_version")

        npm_list = []
        grunt_list = []
        bower_list = []

        temp_dir = getattr(settings, 'BWR_APP_TMP_FOLDER', '.tmp')
        temp_dir = os.path.abspath(temp_dir)

        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        for path, storage in AppDirectoriesFinderBower().list([]):

            abs_path = unicode(os.path.join(storage.location, path))

            if path == 'package.json':
                npm_list.append(abs_path)
            elif path == 'Gruntfile.js':
                grunt_list.append(abs_path)
            elif path == 'bower.json':
                bower_list.append(abs_path)
            else:
                continue

        for path in npm_list:
            self.npm_install(path)

        for path in grunt_list:
            self.grunt_default(path)

        for path in bower_list:
            self.bower_install(path, temp_dir)

        bower_dir = os.path.join(temp_dir, 'bower_components')

        # nothing to clean
        if not os.path.exists(bower_dir):
            print('No components seems to have been installed by bower, exiting.')
            sys.exit(0)

        self.clean_components_to_static_dir(bower_dir)
