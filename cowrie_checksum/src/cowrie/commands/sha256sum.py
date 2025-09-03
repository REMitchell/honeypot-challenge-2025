import hashlib
import os
import getopt

from cowrie.shell.command import HoneyPotCommand
from twisted.python import log

commands = {}

class Command_sha256sum(HoneyPotCommand):
    """
    Minimal implementation of sha256sum
    Supports:
      - computing SHA-256 for one or more files
      - verifying checksums with --check
    """

    def start(self) -> None:
        try:
            optlist, args = getopt.getopt(self.args, "", ["check"])
        except getopt.GetoptError:
            self.errorWrite("sha256sum: invalid option\n")
            self.exit()
            return

        self.check_mode = False
        for opt, _ in optlist:
            if opt == "--check":
                self.check_mode = True

        if not args:
            self.errorWrite("sha256sum: missing file operand\n")
            self.exit()
            return

        if self.check_mode:
            self.check_file(args[0])
        else:
            for fname in args:
                self.hash_file(fname)

        self.exit()

    def hash_file(self, fname: str) -> None:
        path = self.fs.resolve_path(fname, self.protocol.cwd)
        try:
            data = self.fs.file_contents(path)
            h = hashlib.sha256(data).hexdigest()
            self.write(f"{h}  {fname}\n")
        except Exception:
            self.errorWrite(f"sha256sum: {fname}: No such file or directory\n")

    def check_file(self, checksum_file: str) -> None:
        path = self.fs.resolve_path(checksum_file, self.protocol.cwd)
        try:
            lines = self.fs.file_contents(path).decode("utf-8").splitlines()
        except Exception:
            self.errorWrite(f"sha256sum: {checksum_file}: No such file or directory\n")
            return

        for line in lines:
            try:
                checksum, fname = line.strip().split(None, 1)
                fname = fname.strip().lstrip("*")  # support "*filename" too
                path = self.fs.resolve_path(fname, self.protocol.cwd)
                data = self.fs.file_contents(path)
                actual = hashlib.sha256(data).hexdigest()
                if actual == checksum:
                    self.write(f"{fname}: OK\n")
                else:
                    self.write(f"{fname}: FAILED\n")
            except Exception:
                self.write(f"{fname}: FAILED open or read\n")


commands["sha256sum"] = Command_sha256sum
commands["/usr/bin/sha256sum"] = Command_sha256sum
