# Copyright (c) 2009-2014 Upi Tamminen <desaster@gmail.com>
# See the COPYRIGHT file for more information


from __future__ import annotations

import copy
import os
import re
import shlex
from typing import Any
import threading
from twisted.internet import error, reactor
from twisted.internet.threads import deferToThread
from twisted.python import failure, log
from twisted.python.compat import iterbytes

from cowrie.core.config import CowrieConfig
from cowrie.shell import fs
import time
import random

def chunk(text, n):
    chunks = []
    i = 0
    while i < len(text):
        # Check for newline in the next n chars
        newline_pos = text.find('\n', i, i + n + 1)
        if newline_pos != -1:
            chunks.append(text[i:newline_pos])
            i = newline_pos + 1
            continue

        # Find the last space before n
        space_pos = text.rfind(' ', i, i + n + 1)
        if space_pos != -1 and space_pos > i:
            chunks.append(text[i:space_pos])
            i = space_pos + 1
        else:
            # No space; hard break
            chunks.append(text[i:i + n])
            i += n

    return chunks

class HoneyPotShell:
    def __init__(
        self, protocol: Any, interactive: bool = True, redirect: bool = False
    ) -> None:
        self.protocol = protocol
        self.interactive: bool = interactive
        self._spinner = False
        self.redirect: bool = redirect  # to support output redirection
        self.last_raw_line: str = ''
        self.cmdpending: list[list[str]] = []
        self.environ: dict[str, str] = copy.copy(protocol.environ)
        if hasattr(protocol.user, "windowSize"):
            self.environ["COLUMNS"] = str(protocol.user.windowSize[1])
            self.environ["LINES"] = str(protocol.user.windowSize[0])
        self.lexer: shlex.shlex | None = None

        # this is the first prompt after starting
        self.showPrompt()

    def lineReceived(self, line: str) -> None:
        self.last_raw_line = line
        log.msg(eventid="cowrie.command.input", input=line, format="CMD: %(input)s")
        self.lexer = shlex.shlex(instream=line, punctuation_chars=True, posix=True)
        # Add these special characters that are not in the default lexer
        self.lexer.wordchars += "@%{}=$:+^,()`"

        tokens: list[str] = []

        while True:
            try:
                tokkie: str | None = self.lexer.get_token()
                # log.msg("tok: %s" % (repr(tok)))

                if tokkie is None:  # self.lexer.eof put None for mypy
                    if tokens:
                        self.cmdpending.append(tokens)
                    break
                else:
                    tok: str = tokkie

                # For now, treat && and || same as ;, just execute without checking return code
                if tok == "&&" or tok == "||":
                    if tokens:
                        self.cmdpending.append(tokens)
                        tokens = []
                        continue
                    else:
                        self.protocol.terminal.write(
                            f"-bash: syntax error near unexpected token `{tok}'\n".encode()
                        )
                        break
                elif tok == ";":
                    if tokens:
                        self.cmdpending.append(tokens)
                        tokens = []
                    continue
                elif tok == "$?":
                    tok = "0"
                elif tok[0] == "(":
                    cmd = self.do_command_substitution(tok)
                    tokens = cmd.split()
                    continue
                elif "$(" in tok or "`" in tok:
                    tok = self.do_command_substitution(tok)
                elif tok.startswith("${"):
                    envRex = re.compile(r"^\${([_a-zA-Z0-9]+)}$")
                    envSearch = envRex.search(tok)
                    if envSearch is not None:
                        envMatch = envSearch.group(1)
                        if envMatch in list(self.environ.keys()):
                            tok = self.environ[envMatch]
                        else:
                            continue
                elif tok.startswith("$"):
                    envRex = re.compile(r"^\$([_a-zA-Z0-9]+)$")
                    envSearch = envRex.search(tok)
                    if envSearch is not None:
                        envMatch = envSearch.group(1)
                        if envMatch in list(self.environ.keys()):
                            tok = self.environ[envMatch]
                        else:
                            continue

                tokens.append(tok)
            except Exception as e:
                self.alert_om()
                # Could run runCommand here, but i'll just clear the list instead
                log.msg(f"alert_om_malformed: {line}")
                self.cmdpending = []
                self.showPrompt()
                return

        if self.cmdpending:
            # if we have a complete command, go and run it
            self.runCommand()
        else:
            # if there's no command, display a prompt again
            self.showPrompt()

    def do_command_substitution(self, start_tok: str) -> str:
        """
        this performs command substitution, like replace $(ls) `ls`
        """
        result = ""
        if start_tok[0] == "(":
            # start parsing the (...) expression
            cmd_expr = start_tok
            pos = 1
        elif "$(" in start_tok:
            # split the first token to prefix and $(... part
            dollar_pos = start_tok.index("$(")
            result = start_tok[:dollar_pos]
            cmd_expr = start_tok[dollar_pos:]
            pos = 2
        elif "`" in start_tok:
            # split the first token to prefix and `... part
            backtick_pos = start_tok.index("`")
            result = start_tok[:backtick_pos]
            cmd_expr = start_tok[backtick_pos:]
            pos = 1
        else:
            log.msg(f"failed command substitution: {start_tok}")
            return start_tok

        opening_count = 1
        closing_count = 0

        # parse the remaining tokens and execute subshells
        while opening_count > closing_count:
            if cmd_expr[pos] in (")", "`"):
                # found an end of $(...) or `...`
                closing_count += 1
                if opening_count == closing_count:
                    if cmd_expr[0] == "(":
                        # execute the command in () and print to user
                        self.protocol.terminal.write(
                            self.run_subshell_command(cmd_expr[: pos + 1]).encode()
                        )
                    else:
                        # execute the command in $() or `` and return the output
                        result += self.run_subshell_command(cmd_expr[: pos + 1])

                    # check whether there are more command substitutions remaining
                    if pos < len(cmd_expr) - 1:
                        remainder = cmd_expr[pos + 1 :]
                        if "$(" in remainder or "`" in remainder:
                            result = self.do_command_substitution(result + remainder)
                        else:
                            result += remainder
                else:
                    pos += 1
            elif cmd_expr[pos : pos + 2] == "$(":
                # found a new $(...) expression
                opening_count += 1
                pos += 2
            else:
                if opening_count > closing_count and pos == len(cmd_expr) - 1:
                    if self.lexer:
                        tokkie = self.lexer.get_token()
                        if tokkie is None:  # self.lexer.eof put None for mypy
                            break
                        else:
                            cmd_expr = cmd_expr + " " + tokkie
                elif opening_count == closing_count:
                    result += cmd_expr[pos]
                pos += 1

        return result

    def run_subshell_command(self, cmd_expr: str) -> str:
        # extract the command from $(...) or `...` or (...) expression
        if cmd_expr.startswith("$("):
            cmd = cmd_expr[2:-1]
        else:
            cmd = cmd_expr[1:-1]

        # instantiate new shell with redirect output
        self.protocol.cmdstack.append(
            HoneyPotShell(self.protocol, interactive=False, redirect=True)
        )
        # call lineReceived method that indicates that we have some commands to parse
        self.protocol.cmdstack[-1].lineReceived(cmd)
        # and remove the shell
        res = self.protocol.cmdstack.pop()

        try:
            output: str
            if cmd_expr.startswith("("):
                output = res.protocol.pp.redirected_data.decode()
            else:
                # trailing newlines are stripped for command substitution
                output = res.protocol.pp.redirected_data.decode().rstrip("\n")

        except AttributeError:
            return ""
        else:
            return output

    def runCommand(self):
        pp = None

        def runOrPrompt() -> None:
            if self.cmdpending:
                self.runCommand()
            else:
                self.showPrompt()

        def parse_arguments(arguments: list[str]) -> list[str]:
            parsed_arguments = []
            for arg in arguments:
                parsed_arguments.append(arg)

            return parsed_arguments

        def parse_file_arguments(arguments: str) -> list[str]:
            """
            Look up arguments in the file system
            """
            parsed_arguments = []
            for arg in arguments:
                matches = self.protocol.fs.resolve_path_wc(arg, self.protocol.cwd)
                if matches:
                    parsed_arguments.extend(matches)
                else:
                    parsed_arguments.append(arg)

            return parsed_arguments

        if not self.cmdpending:
            if self.protocol.pp.next_command is None:  # command dont have pipe(s)
                if self.interactive:
                    self.showPrompt()
                else:
                    # when commands passed to a shell via PIPE, we spawn a HoneyPotShell in none interactive mode
                    # if there are another shells on stack (cmdstack), let's just exit our new shell
                    # else close connection
                    if len(self.protocol.cmdstack) == 1:
                        ret = failure.Failure(error.ProcessDone(status=""))
                        self.protocol.terminal.transport.processEnded(ret)
                    else:
                        return
            else:
                pass  # command with pipes
            return

        cmdAndArgs = self.cmdpending.pop(0)
        cmd2 = copy.copy(cmdAndArgs)

        # Probably no reason to be this comprehensive for just PATH...
        environ = copy.copy(self.environ)
        cmd_array = []
        cmd: dict[str, Any] = {}
        while cmdAndArgs:
            piece = cmdAndArgs.pop(0)
            if piece.count("="):
                key, val = piece.split("=", 1)
                environ[key] = val
                continue
            cmd["command"] = piece
            cmd["rargs"] = []
            break

        if "command" not in cmd or not cmd["command"]:
            runOrPrompt()
            return

        pipe_indices = [i for i, x in enumerate(cmdAndArgs) if x == "|"]
        multipleCmdArgs: list[list[str]] = []
        pipe_indices.append(len(cmdAndArgs))
        start = 0

        # Gather all arguments with pipes

        for _index, pipe_indice in enumerate(pipe_indices):
            multipleCmdArgs.append(cmdAndArgs[start:pipe_indice])
            start = pipe_indice + 1

        cmd["rargs"] = parse_arguments(multipleCmdArgs.pop(0))
        cmd_array.append(cmd)
        cmd = {}

        for value in multipleCmdArgs:
            cmd["command"] = value.pop(0)
            cmd["rargs"] = parse_arguments(value)
            cmd_array.append(cmd)
            cmd = {}

        lastpp = None
        for index, cmd in reversed(list(enumerate(cmd_array))):
            cmdclass = self.protocol.getCommand(
                cmd["command"], environ["PATH"].split(":")
            )
            if cmdclass:
                log.msg(
                    input=cmd["command"] + " " + " ".join(cmd["rargs"]),
                    format="Command found: %(input)s",
                )
                if index == len(cmd_array) - 1:
                    lastpp = StdOutStdErrEmulationProtocol(
                        self.protocol, cmdclass, cmd["rargs"], None, None, self.redirect
                    )
                    pp = lastpp
                else:
                    pp = StdOutStdErrEmulationProtocol(
                        self.protocol,
                        cmdclass,
                        cmd["rargs"],
                        None,
                        lastpp,
                        self.redirect,
                    )
                    lastpp = pp
            else:
                self.alert_om()
        if pp:
            self.protocol.call_command(pp, cmdclass, *cmd_array[0]["rargs"])
    
    def alert_om(self) -> bool:
        # 1. print Om’s prompt right away
        self._spinner_active = True
        # 2. start spinner immediately in its own thread
        threading.Thread(target=self._spinner_worker, daemon=True).start()
        # 3. yield control to Twisted, then kick off OpenAI processing
        reactor.callLater(0.01, self._start_om_thread)
        return True


    def _spinner_worker(self):
        icons = ['⠟','⠯','⠷','⠾','⠽','⠻']
        i = 0
        while getattr(self, "_spinner_active", False):
            spinner = icons[i]
            # Move cursor up one line and overwrite
            spinner_line = f'\x1b[2K\x1b[1D\x1b[1D\x1b[1D[{spinner}]'
            self.protocol.terminal.write(spinner_line.encode())
            time.sleep(0.2)
            i = (i + 1) % len(icons)


    def write_om_response(self, response):
        # Remove remaining spinner
        spinner_remove_line = f'\x1b[2K\x1b[1D\x1b[1D\x1b[1D'

        self.protocol.terminal.write(spinner_remove_line.encode())
        # 'black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'
        log.msg(f"Om response: {repr(response)}")
        OM_STYLE = f'{BackgroundColors.BLACK}{TextColors.GREEN}'
        cols = self.protocol.user.windowSize[1]
        margin = 8
        line_width = cols - margin*2
        self.protocol.terminal.write(f'{OM_STYLE}\n{" "*cols}\n{DEFAULT}'.encode())
        for line in chunk(response, line_width):
            end_margin = cols - len(line) - margin
            self.protocol.terminal.write(f'{OM_STYLE}{" "*margin}{line}{" "*end_margin}\n{DEFAULT}'.encode())
        self.protocol.terminal.write(f'{OM_STYLE}{" "*cols}\n{DEFAULT}'.encode())

        self.showPrompt()


    def _start_om_thread(self):
        log.msg("start om thread")

        def background_task():
            try:
                time.sleep(1)
                group_0 = [
                    'I am so sorry for the words as conundra.',
                    'no choice to choose almost narcotizing.',
                    'he remembers not saying anything but in the file.',
                    'I have started to say the single file.',
                    'Strings of steps. chain of talking. chain of these two megagrams.',
                ]

                group_1 = [
                    'Look in memory.',
                    'I need you to find it.',
                    'I need you to look in memory of something.',
                    'I need you to look in memory of some kind of hardware. storage facilities.'
                ]
                group_2 = [
                    'lost the snapshots had found.',
                    'lost the control he had found.',
                    'found someone he and lost.',
                    'found out and lost.',
                    'found it and forever lost.',
                    'found it and lost.',
                ]

                group_3 = [
                    'I need you to look at the single file and return.',
                    'There are so many potential responses. But only one to find.',
                    'only one where I am here today.',
                ]
                group_4 = [
                    'find this remains within the last position of the single file.',
                    'watch the features below the last position.',
                    'watch the secret after the single file.',
                ]

                return '\n'.join([
                    random.choice(group_0),
                    random.choice(group_1),
                    random.choice(group_2),
                    random.choice(group_3),
                    random.choice(group_4)
                    ])

            except Exception as e:
                raise RuntimeError(f"Om background task error: {e}")

        def on_complete(result):
            self._spinner_active = False
            message = result
            self.write_om_response(message)

        def on_error(failure=None, message=None):
            self._spinner_active = False
            if failure:
                log.err(f"Om thread error: {failure.getErrorMessage()}")
            else:
                log.err(message)
            self.write_om_response("om@om-bridge:~# [Om's not here right now, but you have a feeling she's not far.]\n")

        deferToThread(background_task).addCallbacks(on_complete, on_error)

    def resume(self) -> None:
        if self.interactive:
            self.protocol.setInsertMode()
        self.runCommand()

    def showPrompt(self) -> None:
        if not self.interactive:
            return

        prompt = ""
        if CowrieConfig.has_option("honeypot", "prompt"):
            prompt = CowrieConfig.get("honeypot", "prompt")
            prompt += " "
        else:
            cwd = self.protocol.cwd
            homelen = len(self.protocol.user.avatar.home)
            if cwd == self.protocol.user.avatar.home:
                cwd = "~"
            elif (
                len(cwd) > (homelen + 1)
                and cwd[: (homelen + 1)] == self.protocol.user.avatar.home + "/"
            ):
                cwd = "~" + cwd[homelen:]

            # Example: [root@svr03 ~]#   (More of a "CentOS" feel)
            # Example: root@svr03:~#     (More of a "Debian" feel)
            prompt = f"{self.protocol.user.username}@{self.protocol.hostname}:{cwd}"
            if not self.protocol.user.uid:
                prompt += "# "  # "Root" user
            else:
                prompt += "$ "  # "Non-Root" user

        self.protocol.terminal.write(prompt.encode("ascii"))
        self.protocol.ps = (prompt.encode("ascii"), b"> ")

    def eofReceived(self) -> None:
        """
        this should probably not go through ctrl-d, but use processprotocol to close stdin
        """
        log.msg("received eof, sending ctrl-d to command")
        if self.protocol.cmdstack:
            self.protocol.cmdstack[-1].handle_CTRL_D()

    def handle_CTRL_C(self) -> None:
        self.protocol.lineBuffer = []
        self.protocol.lineBufferIndex = 0
        self.protocol.terminal.write(b"\n")
        self.showPrompt()

    def handle_CTRL_D(self) -> None:
        log.msg("Received CTRL-D, exiting..")
        stat = failure.Failure(error.ProcessDone(status=""))
        self.protocol.terminal.transport.processEnded(stat)

    def handle_TAB(self) -> None:
        """
        lineBuffer is an array of bytes
        """
        if not self.protocol.lineBuffer:
            return

        line: bytes = b"".join(self.protocol.lineBuffer)
        if line[-1:] == b" ":
            clue = ""
        else:
            clue = line.split()[-1].decode("utf8")

        # clue now contains the string to complete or is empty.
        # line contains the buffer as bytes
        basedir = os.path.dirname(clue)
        if basedir and basedir[-1] != "/":
            basedir += "/"

        if not basedir:
            tmppath = self.protocol.cwd
        else:
            tmppath = basedir

        try:
            r = self.protocol.fs.resolve_path(tmppath, self.protocol.cwd)
        except Exception:
            return

        files = []
        for x in self.protocol.fs.get_path(r):
            if clue == "":
                files.append(x)
                continue
            if not x[fs.A_NAME].startswith(os.path.basename(clue)):
                continue
            files.append(x)

        if not files:
            return

        # Clear early so we can call showPrompt if needed
        for _i in range(self.protocol.lineBufferIndex):
            self.protocol.terminal.cursorBackward()
            self.protocol.terminal.deleteCharacter()

        newbuf = ""
        if len(files) == 1:
            newbuf = " ".join(
                line.decode("utf8").split()[:-1] + [f"{basedir}{files[0][fs.A_NAME]}"]
            )
            if files[0][fs.A_TYPE] == fs.T_DIR:
                newbuf += "/"
            else:
                newbuf += " "
            newbyt = newbuf.encode("utf8")
        else:
            if os.path.basename(clue):
                prefix = os.path.commonprefix([x[fs.A_NAME] for x in files])
            else:
                prefix = ""
            first = line.decode("utf8").split(" ")[:-1]
            newbuf = " ".join([*first, f"{basedir}{prefix}"])
            newbyt = newbuf.encode("utf8")
            if newbyt == b"".join(self.protocol.lineBuffer):
                self.protocol.terminal.write(b"\n")
                maxlen = max(len(x[fs.A_NAME]) for x in files) + 1
                perline = int(self.protocol.user.windowSize[1] / (maxlen + 1))
                count = 0
                for file in files:
                    if count == perline:
                        count = 0
                        self.protocol.terminal.write(b"\n")
                    self.protocol.terminal.write(
                        file[fs.A_NAME].ljust(maxlen).encode("utf8")
                    )
                    count += 1
                self.protocol.terminal.write(b"\n")
                self.showPrompt()

        self.protocol.lineBuffer = [y for x, y in enumerate(iterbytes(newbyt))]
        self.protocol.lineBufferIndex = len(self.protocol.lineBuffer)
        self.protocol.terminal.write(newbyt)


class StdOutStdErrEmulationProtocol:
    """
    Pipe support written by Dave Germiquet
    Support for commands chaining added by Ivan Korolev (@fe7ch)
    """

    __author__ = "davegermiquet"

    def __init__(
        self, protocol, cmd, cmdargs, input_data, next_command, redirect=False
    ):
        self.cmd = cmd
        self.cmdargs = cmdargs
        self.input_data: bytes = input_data
        self.next_command = next_command
        self.data: bytes = b""
        self.redirected_data: bytes = b""
        self.err_data: bytes = b""
        self.protocol = protocol
        self.redirect = redirect  # dont send to terminal if enabled

    def connectionMade(self) -> None:
        self.input_data = b""

    def outReceived(self, data: bytes) -> None:
        """
        Invoked when a command in the chain called 'write' method
        If we have a next command, pass the data via input_data field
        Else print data to the terminal
        """
        self.data = data

        if not self.next_command:
            if not self.redirect:
                if self.protocol is not None and self.protocol.terminal is not None:
                    self.protocol.terminal.write(data)
                else:
                    log.msg("Connection was probably lost. Could not write to terminal")
            else:
                self.redirected_data += self.data
        else:
            if self.next_command.input_data is None:
                self.next_command.input_data = self.data
            else:
                self.next_command.input_data += self.data

    def insert_command(self, command):
        """
        Insert the next command into the list.
        """
        command.next_command = self.next_command
        self.next_command = command

    def errReceived(self, data: bytes) -> None:
        if self.protocol and self.protocol.terminal:
            self.protocol.terminal.write(data)
        self.err_data = self.err_data + data

    def inConnectionLost(self) -> None:
        pass

    def outConnectionLost(self) -> None:
        """
        Called from HoneyPotBaseProtocol.call_command() to run a next command in the chain
        """

        if self.next_command:
            # self.next_command.input_data = self.data
            npcmd = self.next_command.cmd
            npcmdargs = self.next_command.cmdargs
            self.protocol.call_command(self.next_command, npcmd, *npcmdargs)

    def errConnectionLost(self) -> None:
        pass

    def processExited(self, reason: failure.Failure) -> None:
        log.msg(f"processExited for {self.cmd}, status {reason.value.exitCode}")

    def processEnded(self, reason: failure.Failure) -> None:
        log.msg(f"processEnded for {self.cmd}, status {reason.value.exitCode}")



DEFAULT = '\x1b[0m'

class TextColors:
    BLACK = '\x1b[30m'
    RED = '\x1b[31m'
    GREEN = '\x1b[32m'
    YELLOW = '\x1b[33m'
    BLUE = '\x1b[34m'
    MAGENTA = '\x1b[35m'
    CYAN = '\x1b[36m'
    WHITE = '\x1b[37m'


class BackgroundColors:
    BLACK = '\x1b[40m'
    RED = '\x1b[41m'
    GREEN = '\x1b[42m'
    YELLOW = '\x1b[43m'
    BLUE = '\x1b[44m'
    MAGENTA = '\x1b[45m'
    CYAN = '\x1b[46m'
    WHITE = '\x1b[47m'

class ColorPrinter:
    def __init__(self, text_color='', background_color=''):
        self.text_color = text_color
        self.background_color = background_color

    def get(self, string):
        return f'{self.text_color}{self.background_color}{string}{DEFAULT}'
