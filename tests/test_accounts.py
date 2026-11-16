"""Main account selection for both launchers; mock CLIs only, no login, key or model calls."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1]
MOCK = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
tool, args = Path(sys.argv[0]).name, sys.argv[1:]
folder = os.environ.get('CLAUDE_CONFIG_DIR')
if tool == 'claude' and args[:2] == ['auth', 'status']:
    print(json.dumps(dict(loggedIn=True, email=('team' if folder else 'me') + '@example.org',
                          subscriptionType='team' if folder else 'max')))
    raise SystemExit(0)
if tool == 'claude' and '--version' in args: print('2.1.314'); raise SystemExit(0)
if tool == 'claude' and '--help' in args: print('--name --disallowedTools --system-prompt-snapshot'); raise SystemExit(0)
record = dict(tool=tool, args=args, config_dir=folder)
with Path(os.environ['MOCK_CALLS']).open('a') as out:
    out.write(json.dumps(record) + '\n')
if tool == 'ocx':
    state = Path(os.environ['OCX_STATE'])
    keys = json.loads(state.read_text())
    if args[:2] == ['account', 'list']:
        print(json.dumps(dict(accounts=keys)))
    elif args[:2] == ['account', 'use']:
        if os.environ.get('OCX_REFUSE'): sys.exit('refused')
        for key in keys: key['active'] = key['id'] == args[3]
        state.write_text(json.dumps(keys))
elif tool == 'tmux':
    if os.environ.get('TMUX_RECORD_ONLY'):
        if args[0] == 'split-window': print('%1')
        raise SystemExit(0)
    if args[0] == 'has-session': raise SystemExit(1)
    if args[0] in ('new-session', 'split-window'):
        result = subprocess.run(['bash', '-c', args[-1]], cwd=args[args.index('-c') + 1], stdin=subprocess.DEVNULL)
        if args[0] == 'split-window': print('%1')
        raise SystemExit(result.returncode)
else:
    print(json.dumps(record))
'''
KEYS = [dict(id='aaaa1111', label='${ANTHROPIC_API_KEY_INDIVIDUAL}', masked='${ANTHROPIC_API_KEY_INDIVIDUAL}', active=False),
        dict(id='bbbb2222', label='TEAM', masked='sk-a****0000', active=True)]


class Accounts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='main-accounts-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mock = self.root / 'mock'
        mock.mkdir()
        for name in ('claude', 'codex', 'ocx', 'tmux'):
            (mock / name).write_text(MOCK)
            (mock / name).chmod(0o755)
        self.calls = self.root / 'calls.jsonl'
        self.state = self.root / 'ocx-state.json'
        self.state.write_text(json.dumps(KEYS))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(
            ('LLM_', 'CLAUDE_', 'ANTHROPIC_', 'ORCHESTRATOR_', 'GIT_', 'DEEPSEEK_'))}
        self.env.update(HOME=str(self.root), PATH=str(mock) + os.pathsep + os.environ['PATH'],
                        LLM_WORKER_CONF_DIR=str(self.root / 'conf'), XDG_STATE_HOME=str(self.root / 'state'),
                        LLM_POOL_HOME=str(self.root / 'pools'), LLM_MODEL='mock-default', PYTHONDONTWRITEBYTECODE='1',
                        MOCK_CALLS=str(self.calls), OCX_STATE=str(self.state))
        self.bin = self.root / 'installed'
        self.tool(KIT / 'install.sh', '--non-interactive', '--prefix', self.bin)
        self.team = self.root / '.claude-team'

    def tool(self, *args, env=None, code=0, cwd=None):
        result = subprocess.run(list(map(str, args)), env=env or self.env, cwd=cwd or KIT,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def main(self, kind, *args, env=None):
        return json.loads(self.tool(self.bin / (kind + '-main'), *args, env=env).stdout)

    def recorded(self, tool):
        if not self.calls.is_file():
            return []
        return [x for x in map(json.loads, self.calls.read_text().splitlines()) if x['tool'] == tool]

    def register(self, link=True):
        source = self.root / '.claude'
        (source / 'projects').mkdir(parents=True)
        (source / 'CLAUDE.md').write_text('shared instructions\n')
        (source / 'settings.json').write_text('{"theme": "auto"}\n')
        self.tool(self.bin / 'llm-account', 'init')
        if link:
            self.tool(self.bin / 'llm-account', 'link', 'team')

    def status_line(self, result):
        args = result['args']
        return json.loads(args[args.index('--settings') + 1])['statusLine']['command']

    def test_without_registered_accounts_nothing_changes_and_an_explicit_account_fails(self):
        inherited = dict(self.env, CLAUDE_CONFIG_DIR=str(self.root / 'mine'))
        result = self.main('claude', '-p', 'fixture', env=inherited)
        self.assertNotIn('--settings', result['args'])
        self.assertEqual(result['config_dir'], str(self.root / 'mine'))
        result = self.main('codex', 'resume', '--last')
        self.assertFalse(any('terminal_title' in x for x in result['args']))
        self.assertEqual(self.recorded('ocx'), [])
        for kind in ('claude', 'codex'):
            failed = self.tool(self.bin / (kind + '-main'), '--account', 'team', code=2)
            self.assertFalse(failed.stdout)
            self.assertIn('unknown account', failed.stderr)

    def test_claude_account_selects_the_directory_and_labels_the_status_line(self):
        self.register()
        result = self.main('claude', '--account', 'team', '--resume', 'existing')
        self.assertEqual(result['config_dir'], str(self.team))
        self.assertEqual(self.status_line(result), "printf %s 'Team · team@example.org'")
        self.assertIn('--resume', result['args'])
        self.assertNotIn('--account', result['args'])
        # INDIVIDUAL is Claude Code's default directory even when another one is inherited.
        for alias in ('personal', 'indiv', 'Individual'):
            result = self.main('claude', '--account=' + alias, env=dict(self.env, CLAUDE_CONFIG_DIR=str(self.team)))
            self.assertIsNone(result['config_dir'])
            self.assertEqual(self.status_line(result), "printf %s 'Personal · me@example.org'")
        # The label is display text only: without one the account name is shown, and --account accepts either.
        registry = self.root / 'conf/accounts.json'
        data = json.loads(registry.read_text())
        data['accounts']['TEAM']['label'] = 'Lab seat'
        del data['accounts']['INDIVIDUAL']['label']
        registry.write_text(json.dumps(data))
        self.assertEqual(self.status_line(self.main('claude', '--account', 'lab seat')), "printf %s 'Lab seat · team@example.org'")
        self.assertEqual(self.status_line(self.main('claude', '--account', 'team')), "printf %s 'Lab seat · team@example.org'")
        self.assertEqual(self.status_line(self.main('claude', '--account', 'indiv')), "printf %s 'INDIVIDUAL · me@example.org'")

    def test_unattended_start_keeps_the_current_account_and_shows_its_real_login(self):
        self.register()
        result = self.main('claude', '-p', 'fixture', env=dict(self.env, CLAUDE_CONFIG_DIR=str(self.team)))
        self.assertEqual(result['config_dir'], str(self.team))
        self.assertEqual(self.status_line(result), 'printf %s team@example.org')
        result = self.main('claude', '--settings', '{"theme":"dark"}', '-p', 'fixture')
        self.assertEqual(result['args'].count('--settings'), 1)
        self.assertIsNone(result['config_dir'])
        result = self.main('codex', 'exec', 'fixture')
        self.assertIn('tui.terminal_title=[]', result['args'])
        self.assertFalse([x for x in self.recorded('ocx') if x['args'][:2] == ['account', 'use']])

    def test_link_shares_instructions_and_history_but_copies_settings(self):
        self.register(link=False)
        failed = self.tool(self.bin / 'claude-main', '--account', 'team', code=2)
        self.assertIn('llm-account link TEAM', failed.stderr)
        self.assertEqual(self.recorded('claude'), [])
        out = self.tool(self.bin / 'llm-account', 'link', 'TEAM').stdout
        self.assertIn('created', out)
        for item in ('CLAUDE.md', 'projects'):
            self.assertEqual((self.team / item).resolve(), (self.root / '.claude' / item).resolve())
            self.assertTrue((self.team / item).is_symlink())
        self.assertFalse((self.team / 'settings.json').is_symlink())
        (self.team / 'settings.json').write_text('{"theme": "dark"}\n')
        self.assertIn('nothing to do', self.tool(self.bin / 'llm-account', 'link', 'team').stdout)
        self.assertEqual((self.team / 'settings.json').read_text(), '{"theme": "dark"}\n')
        self.assertEqual((self.root / '.claude/settings.json').read_text(), '{"theme": "auto"}\n')
        listing = self.tool(self.bin / 'llm-account', 'list').stdout
        self.assertIn('team@example.org', listing)
        self.assertIn('TEAM  shown as Team', listing)
        self.assertEqual(self.tool(self.bin / 'llm-account', 'current').stdout.strip(), 'Team')

    def test_codex_account_switches_the_active_key_and_keeps_the_title(self):
        self.register()
        run = self.tool(self.bin / 'codex-main', '--account', 'indiv', 'resume', '--', '--account', 'team')
        args = json.loads(run.stdout)['args']
        self.assertIn(['account', 'use', 'anthropic-apikey', 'aaaa1111'], [x['args'] for x in self.recorded('ocx')])
        self.assertLess(args.index('tui.terminal_title=[]'), args.index('--'))
        self.assertEqual(args[args.index('--') + 1:], ['--account', 'team'])
        self.assertIn('Account: Personal', run.stderr)
        self.assertEqual(self.tool(self.bin / 'llm-account', 'current').stdout.strip(), 'Personal')
        # The already active key is not switched again.
        before = len(self.recorded('ocx'))
        self.main('codex', '--account', 'INDIVIDUAL')
        self.assertFalse([x for x in self.recorded('ocx')[before:] if x['args'][:2] == ['account', 'use']])

    def test_unknown_account_or_refused_switch_stops_before_the_native_cli(self):
        self.register()
        for kind in ('claude', 'codex'):
            failed = self.tool(self.bin / (kind + '-main'), '--account', 'school', code=2)
            self.assertIn('unknown account', failed.stderr)
            failed = self.tool(self.bin / (kind + '-main'), '--account', code=2)
            self.assertIn('--account requires a name', failed.stderr)
        failed = self.tool(self.bin / 'codex-main', '--account', 'indiv', env=dict(self.env, OCX_REFUSE='1'), code=2)
        self.assertIn('refused', failed.stderr)
        self.state.write_text(json.dumps(KEYS[1:]))
        failed = self.tool(self.bin / 'codex-main', '--account', 'indiv', code=2)
        self.assertIn('no anthropic-apikey key is labelled', failed.stderr)
        self.assertEqual(self.recorded('claude') + self.recorded('codex'), [])

    def test_duo_launchers_hand_the_account_to_the_main(self):
        self.register()
        repo = self.root / 'project'
        repo.mkdir()
        (repo / 'source.txt').write_text('base')
        self.tool('git', 'init', '-q', cwd=repo)
        self.tool('git', 'add', 'source.txt', cwd=repo)
        self.tool('git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@local', 'commit', '-qm', 'base', cwd=repo)
        self.tool(self.bin / 'codex-duo', '--headless', '-w', '1', '--account', 'personal', cwd=repo)
        self.assertIn('tui.terminal_title=[]', self.recorded('codex')[-1]['args'])
        self.assertIn(['account', 'use', 'anthropic-apikey', 'aaaa1111'], [x['args'] for x in self.recorded('ocx')])
        self.tool(self.bin / 'claude-duo', '--headless', '-w', '1', '--account', 'team', cwd=repo)
        self.assertEqual(self.recorded('claude')[-1]['config_dir'], str(self.team))
        self.tool(self.bin / 'claude-duo', '--manual', '--account', 'team', '-w', '1', repo)
        main, worker = self.recorded('claude')[-2:]
        self.assertEqual(main['config_dir'], str(self.team))
        self.assertIn('--settings', main['args'])
        self.assertIsNone(worker['config_dir'])
        self.tool(self.bin / 'claude-duo', '--headless', '-w', '1', '--account', 'school', cwd=repo, code=1)
        # A pane session shows the proxy's current key, which can change after the session starts.
        self.tool(self.bin / 'codex-duo', '--panes', '--no-attach', '-w', '1', '--account', 'team', cwd=repo,
                  env=dict(self.env, TMUX_RECORD_ONLY='1'))
        status = [x['args'] for x in self.recorded('tmux') if x['args'][0] == 'set-option']
        self.assertEqual(len(status), 1)
        self.assertIn('llm-account current', status[0][-1])
        started = next(x['args'] for x in self.recorded('tmux') if x['args'][0] == 'new-session')
        self.assertIn('--account TEAM', started[-1])


if __name__ == '__main__':
    unittest.main()
