"""Stage the Arch payload under /usr, independent of the build environment."""

import sys
import sysconfig

from installer import install
from installer.destinations import SchemeDictionaryDestination
from installer.sources import WheelFile


paths = sysconfig.get_paths(scheme='posix_prefix', vars={'base': '/usr', 'platbase': '/usr'})
scheme = {key: paths[key] for key in ('purelib', 'platlib', 'scripts', 'data')}
scheme['headers'] = paths['include'] + '/gillete'
with WheelFile.open(sys.argv[2]) as source:
    source.validate_record(validate_contents=True)
    destination = SchemeDictionaryDestination(scheme, interpreter='/usr/bin/python', script_kind='posix',
                                               bytecode_optimization_levels=(0, 1), destdir=sys.argv[1])
    install(source, destination, {})
