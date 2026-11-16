"""Named main accounts: a Claude config directory and a Codex API-key pool entry. No credentials are read."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from _kit_env import configure
configure()

PROVIDER = 'anthropic-apikey'
KEY_PREFIX = 'ANTHROPIC_API_KEY_'
SHARED = ('CLAUDE.md', 'projects')  # linked into an account directory; settings.json is copied
TEMPLATE = {'accounts': {'INDIVIDUAL': {'label': 'Personal', 'aliases': ['personal', 'indiv'], 'claude_config_dir': ''},
                         'TEAM': {'label': 'Team', 'aliases': [], 'claude_config_dir': '~/.claude-team'}}}


def path():
    return Path(os.environ['LLM_WORKER_CONF_DIR']) / 'accounts.json'


def registry():
    """Registered accounts by name; empty until the user opts in with llm-account init."""
    if not path().is_file():
        return {}
    accounts = json.loads(path().read_text()).get('accounts', {})
    for name in accounts:
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', name):
            raise ValueError('account names are uppercase identifiers: ' + repr(name))
    return accounts


def label(name, accounts=None):
    """Text shown for an account (status line, title, menu); a key no account owns shows as itself."""
    entry = (registry() if accounts is None else accounts).get(name) or {}
    return entry.get('label') or name


def resolve(value, accounts=None):
    accounts = registry() if accounts is None else accounts
    wanted = value.strip().lower()
    for name, entry in accounts.items():
        if wanted in [name.lower(), (entry.get('label') or name).lower(), *(alias.lower() for alias in entry.get('aliases', []))]:
            return name
    raise ValueError('unknown account ' + repr(value) + '; registered: ' + (', '.join(accounts) or 'none (run llm-account init)'))


def take_account(args):
    """Remove --account from launcher arguments before --; later arguments belong to the native CLI."""
    value, rest = None, []
    args = iter(args)
    for arg in args:
        if arg == '--':
            rest += [arg, *args]
            break
        if arg == '--account':
            value = next(args, '')
        elif arg.startswith('--account='):
            value = arg.split('=', 1)[1]
        else:
            rest.append(arg)
            continue
        if not value:
            raise ValueError('--account requires a name')
    return value, rest


def interactive():
    return sys.stdin.isatty() and sys.stderr.isatty()


def ask(prompt):
    """One answer from the terminal; Ctrl+C or end of input cancels the launch instead of a traceback."""
    sys.stderr.write(prompt)
    sys.stderr.flush()
    try:
        answer = sys.stdin.readline()
    except KeyboardInterrupt:
        answer = ''
    if not answer:
        sys.stderr.write('\n')
        raise ValueError('account selection cancelled')
    return answer.strip()


def choose(kind, value=None):
    """--account wins; a terminal without it asks. None keeps whatever account is in effect now."""
    accounts = registry()
    if value:
        return resolve(value, accounts)
    if not accounts or not interactive():
        return None
    names = list(accounts)
    shown = [label(name, accounts) for name in names]
    width = max(map(len, shown))
    sys.stderr.write('Account for this ' + kind + ' session:\n')
    for index, (text, detail) in enumerate(zip(shown, describe(kind, names, accounts)), 1):
        sys.stderr.write('  ' + str(index) + ') ' + text.ljust(width) + ('  ' + detail if detail else '') + '\n')
    while True:
        answer = ask('Choose [1-' + str(len(names)) + ' or a name]: ')
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        try:
            return resolve(answer, accounts)
        except ValueError:
            pass


def describe(kind, names, accounts):
    if kind == 'claude':
        folders = [claude_dir(name, accounts) for name in names]
        return [claude_identity(folder) if folder is None or folder.is_dir() else 'directory not created' for folder in folders]
    try:
        current = codex_current(accounts)
    except ValueError:
        return ['' for _ in names]
    return ['active now' if name == current else '' for name in names]


# ---------------------------------------------------------------- Claude: one config directory per account

def claude_dir(name, accounts=None):
    """An account's CLAUDE_CONFIG_DIR, or None for Claude Code's default directory."""
    value = (registry() if accounts is None else accounts)[name].get('claude_config_dir') or ''
    return Path(value).expanduser() if value else None


def claude_identity(folder=None):
    """The login Claude Code itself reports for a config directory (None: the default one)."""
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CONFIG_DIR'}
    if folder:
        env['CLAUDE_CONFIG_DIR'] = str(folder)
    try:
        data = json.loads(subprocess.run(['claude', 'auth', 'status'], env=env, capture_output=True, text=True,
                                         timeout=30, stdin=subprocess.DEVNULL).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 'login unknown'
    if not isinstance(data, dict) or not data.get('loggedIn'):
        return 'not logged in'
    return data.get('email') or 'logged in'


def link(name, accounts=None):
    """Create an account's directory: instructions and session history are links, settings a copy."""
    target, source, done = claude_dir(name, accounts), Path.home() / '.claude', []
    if target is None or target.resolve() == source.resolve():
        return done
    if not target.is_dir():
        target.mkdir(parents=True, mode=0o700)
        done.append('created ' + str(target))
    for item in SHARED:
        if (source / item).exists() and not (target / item).exists() and not (target / item).is_symlink():
            (target / item).symlink_to(source / item)
            done.append('linked ' + item + ' -> ' + str(source / item))
    if (source / 'settings.json').is_file() and not (target / 'settings.json').exists():
        shutil.copy2(source / 'settings.json', target / 'settings.json')
        done.append('copied settings.json')
    return done


def ensure_claude_dir(name, accounts=None):
    target = claude_dir(name, accounts)
    if target is None or target.is_dir():
        return
    command = 'llm-account link ' + name
    if not interactive():
        raise ValueError(str(target) + ' does not exist; run: ' + command)
    if ask(str(target) + ' does not exist. Create it now (links ' + ', '.join(SHARED)
           + ' from ~/.claude, copies settings.json)? [y/N] ').lower() not in ('y', 'yes'):
        raise ValueError('account directory not created; run: ' + command)
    for line in link(name, accounts):
        sys.stderr.write('  ' + line + '\n')


def claude_launch(value=None):
    """(account, config directory, --settings JSON) for claude-main; empty strings leave that part unchanged."""
    accounts = registry()
    name = choose('claude', value)
    if not accounts:
        return '', '', ''
    if name:
        ensure_claude_dir(name, accounts)
        folder = claude_dir(name, accounts)
        text = label(name, accounts) + ' · ' + claude_identity(folder)
    else:
        folder, text = None, claude_identity(os.environ.get('CLAUDE_CONFIG_DIR'))
    settings = {'statusLine': {'type': 'command', 'command': 'printf %s ' + shlex.quote(text)}}
    return name or '', str(folder or ''), json.dumps(settings, ensure_ascii=False)


# ---------------------------------------------------------------- Codex: the proxy's active API key

def ocx(*args):
    try:
        result = subprocess.run(['ocx', *args], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('ocx ' + ' '.join(args[:2]) + ' could not run: ' + str(exc))
    if result.returncode != 0:
        raise ValueError('ocx ' + ' '.join(args[:2]) + ' failed: ' + (result.stderr or result.stdout).strip()[:300])
    return result.stdout


def codex_keys():
    return json.loads(ocx('account', 'list', PROVIDER, '--json')).get('accounts', [])


def key_labels(name, entry):
    """A pool key belongs to an account by its label or by the ${VARIABLE} reference it was registered with."""
    return {entry.get('codex_key') or name, name, '${' + KEY_PREFIX + name + '}'}


def codex_key(name, accounts=None):
    wanted = key_labels(name, (registry() if accounts is None else accounts)[name])
    found = [key for key in codex_keys() if key.get('label') in wanted or key.get('masked') in wanted]
    if len(found) != 1:
        raise ValueError(('no ' if not found else 'more than one ') + PROVIDER + ' key is labelled '
                         + ' or '.join(sorted(wanted)) + '; see: ocx account list ' + PROVIDER)
    return found[0]


def codex_use(name):
    """Make the account's key active. The switch is proxy-wide: other running Codex sessions follow it."""
    key = codex_key(name)
    if not key.get('active'):
        ocx('account', 'use', PROVIDER, key['id'])
        key = codex_key(name)
        if not key.get('active'):
            raise ValueError('ocx did not activate the ' + name + ' key')
    return key


def codex_current(accounts=None):
    """Account of the active key, or that key's own label when no registered account owns it."""
    accounts = registry() if accounts is None else accounts
    active = next((key for key in codex_keys() if key.get('active')), None)
    if active is None:
        return ''
    for name, entry in accounts.items():
        if {active.get('label'), active.get('masked')} & key_labels(name, entry):
            return name
    return active.get('label') or active.get('masked') or ''


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('choose', 'claude'))
    parser.add_argument('--account')
    args = parser.parse_args()
    try:
        if args.action == 'choose':
            chosen = choose('claude', args.account)
            if chosen:
                ensure_claude_dir(chosen)
            print(chosen or '')
        else:
            print('\n'.join(claude_launch(args.account)))
    except ValueError as exc:
        parser.exit(2, 'account: ' + str(exc) + '\n')
    except KeyboardInterrupt:
        parser.exit(130, '\n')
