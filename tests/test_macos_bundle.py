"""Check archive boundaries and Mach-O portability without needing a Mac or models."""
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
import build_macos


class MacBundleTests(unittest.TestCase):
    def test_extract_regular_file_and_reject_escaping_members(self):
        for name, kind, link in [('python/file', tarfile.REGTYPE, ''),
                                 ('../outside', tarfile.REGTYPE, ''),
                                 ('python/link', tarfile.SYMTYPE, '../../outside'),
                                 ('python/link', tarfile.LNKTYPE, '../outside'),
                                 ('device', tarfile.CHRTYPE, '')]:
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / 'runtime.tar'
                member = tarfile.TarInfo(name)
                member.type, member.linkname = kind, link
                member.size = 2 if kind == tarfile.REGTYPE else 0
                with tarfile.open(archive, 'w') as package:
                    package.addfile(member, io.BytesIO(b'ok') if member.size else None)
                if name == 'python/file':
                    build_macos.extract(archive, root / 'out')
                    self.assertEqual((root / 'out/python/file').read_bytes(), b'ok')
                else:
                    with self.assertRaises(ValueError):
                        build_macos.extract(archive, root / 'out')
                self.assertFalse((root / 'outside').exists())

    def test_portability_checks_dependencies_not_universal_headers_or_self_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'library.so'
            binary.write_bytes(b'\xcf\xfa\xed\xfe')
            identity = '/build/machine/library.so'
            report = (f'{binary} (architecture x86_64):\n'
                      f'\t{identity} (compatibility version 1.0.0)\n'
                      '\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'
                      f'{binary} (architecture arm64):\n'
                      '\t@rpath/libc++.dylib (compatibility version 1.0.0)\n')
            def output(command, **kwargs):
                return report if command[1] == '-L' else f'{binary}:\n{identity}\n'
            with patch.object(build_macos.subprocess, 'check_output', side_effect=output):
                build_macos.verify_links(directory)
                report += '\t/opt/homebrew/lib/libexample.dylib (compatibility version 1.0.0)\n'
                with self.assertRaisesRegex(ValueError, 'Non-portable library'):
                    build_macos.verify_links(directory)


if __name__ == '__main__':
    unittest.main()
