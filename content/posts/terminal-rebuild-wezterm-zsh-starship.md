---
title: Rebuilding My Terminal From Scratch — wezterm, zsh, starship, fzf, zoxide
date: 2026-10-20
draft: true
tags:
- Linux
- DevOps
keywords:
- wezterm zsh starship setup
- zshrc history completion setup
- fzf zsh keybindings ctrl-r ctrl-t alt-c
- zoxide replace cd
- eza bat ripgrep aliases
- fdfind batcat ubuntu
categories:
- deep-dive
summary: Two days of rebuilding my shell setup on Ubuntu — the tools, the zshrc, the
  gotchas (fdfind/batcat names, starship install path, losing a zshrc to a bad paste)
  and the drills I used to make it stick.
ShowToc: true
---

## Why bother

I'd been living in default bash with a few aliases for years. Every time I watched someone fly through a terminal, the difference wasn't typing speed. It was that they never scrolled back through history, never typed a full path, and never `cd ../../..`-ed their way anywhere.

So I spent two evenings rebuilding the stack and kept a log. This is that log, cleaned up.

## The stack

```
  +-------------------------------------------------------+
  | wezterm               terminal emulator, Lua config    |
  |  +-------------------------------------------------+  |
  |  | zsh (login shell)                               |  |
  |  |   history / completion / options / keybinds    |  |
  |  |   aliases --> eza, bat, rg, fd                  |  |
  |  |   zoxide  --> replaces cd (frecency jumps)      |  |
  |  |   fzf     --> Ctrl-R / Ctrl-T / Alt-C widgets   |  |
  |  |   starship --> prompt, initialised last         |  |
  |  +-------------------------------------------------+  |
  +-------------------------------------------------------+
```

## Day 1: install

What I ended up with on Ubuntu:

| Tool | Version | Note |
|------|---------|------|
| zsh | distro | made default with `chsh` |
| ripgrep | 14.1.0 | `rg` |
| fd-find | 9.0.0 | binary is `fdfind` on Debian/Ubuntu |
| bat | 0.24.0 | binary is `batcat` on Debian/Ubuntu |
| eza | 0.18.2 | from the eza deb repo |
| zoxide | 0.9.9 | smarter `cd` |
| fzf | 0.72.0 | from git |
| starship | 1.25.1 | in `~/.local/bin` |

```bash
sudo apt update && sudo apt install -y zsh git curl build-essential
sudo apt install -y ripgrep fd-find bat
git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf && ~/.fzf/install --all

sudo mkdir -p /etc/apt/keyrings
wget -qO- https://raw.githubusercontent.com/eza-community/eza/main/deb.asc \
  | sudo gpg --dearmor -o /etc/apt/keyrings/gierens.gpg
echo "deb [signed-by=/etc/apt/keyrings/gierens.gpg] http://deb.gierens.de stable main" \
  | sudo tee /etc/apt/sources.list.d/gierens.list
sudo apt update && sudo apt install -y eza

curl -sS https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | bash
curl -sS https://starship.rs/install.sh | sh -s -- -b ~/.local/bin -y

chsh -s "$(which zsh)"
```

On a newer distro you can skip most of the curl-pipes. Debian trixie packages `zsh eza bat fd-find ripgrep zoxide fzf starship` directly. They're older than upstream: in my test container that meant fzf 0.60, zoxide 0.9.7 and starship 1.22.1. That's still new enough for everything below.

wezterm just needs to start zsh as a login shell. `~/.wezterm.lua`:

```lua
local wezterm = require 'wezterm'
local config = wezterm.config_builder()

config.default_prog = { '/usr/bin/zsh', '-l' }

return config
```

Gotchas from day 1:

- **The default starship install didn't land anywhere on my PATH.** Passing `-b ~/.local/bin -y` fixed it. `~/.local/bin` was already on PATH, so nothing else changed.
- **`fd` and `bat` have different binary names on Debian/Ubuntu** (`fdfind`, `batcat`) because of name clashes with older packages. Alias them, or every tutorial you copy from will break.

Sanity check:

```bash
echo $SHELL && starship --version && rg --version && fdfind --version \
  && batcat --version && eza --version && zoxide --version && fzf --version
```

## Day 2: the zshrc

This is the whole file. The order matters at the bottom: zoxide and fzf first, starship last.

```zsh
typeset -U path
path=("$HOME/.local/bin" $path)

HISTFILE="$HOME/.zsh_history"
HISTSIZE=50000
SAVEHIST=50000
setopt SHARE_HISTORY HIST_IGNORE_ALL_DUPS HIST_IGNORE_SPACE HIST_REDUCE_BLANKS

autoload -Uz compinit && compinit
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Za-z}'
zstyle ':completion:*' list-colors "${(s.:.)LS_COLORS}"

setopt AUTO_CD AUTO_PUSHD CORRECT INTERACTIVE_COMMENTS

bindkey -e
autoload -Uz up-line-or-beginning-search down-line-or-beginning-search
zle -N up-line-or-beginning-search
zle -N down-line-or-beginning-search
bindkey '^[[A' up-line-or-beginning-search
bindkey '^[[B' down-line-or-beginning-search

alias ls='eza --group-directories-first'
alias ll='eza -la --git --group-directories-first'
alias lt='eza --tree --level=2'
alias cat='batcat --paging=never'
alias fd='fdfind'
alias grep='rg'
alias g='git'
alias gs='git status -sb'
alias gd='git diff'
alias gl='git log --oneline --graph --decorate -20'
alias cp='cp -i'
alias mv='mv -i'
alias rm='rm -i'
alias reload='source ~/.zshrc'

eval "$(zoxide init zsh --cmd cd)"
source <(fzf --zsh)
export FZF_CTRL_T_OPTS="--preview 'batcat --color=always --line-range :200 {}' --bind 'ctrl-/:toggle-preview'"
eval "$(starship init zsh)"
```

I checked it in a clean Debian trixie container. `zsh -n` is happy, and an interactive shell loads it and ends up with the bindings below.

| Trigger | Result |
|---------|--------|
| `Ctrl-R` | fuzzy history search (`fzf-history-widget`) |
| `Ctrl-T` | fuzzy file picker with bat preview |
| `Alt-C` | fuzzy cd (`fzf-cd-widget`) |
| `Ctrl-/` | toggle the preview pane inside fzf |
| Up / Down | history filtered by what you've already typed |
| `cd <fragment>` | zoxide jump to the best-ranked match |
| bare directory name | auto-cd |
| `ll` | eza listing with a git status column |

Two choices here will bite someone. `alias grep='rg'` breaks any copy-pasted `grep -E` (rg treats `-E` as encoding). When I need real grep I type `command grep`. And `cd` is now zoxide, so `cd foo` will happily jump somewhere other than `./foo` if `./foo` doesn't exist.

## The gotcha that cost me a zshrc

My first attempt: open `.zshrc` in an editor, paste a big block, save. The paste got mangled and I lost most of the file. Since then I replace config files with a heredoc and keep a backup:

```bash
cp ~/.zshrc ~/.zshrc.bak
cat > ~/.zshrc << 'EOF'
# ... whole file ...
EOF
source ~/.zshrc
```

The quoted `'EOF'` stops the shell from expanding `$HOME` and friends inside the block, so what lands in the file is exactly what you pasted.

## Drills

Config is the easy part. Habits are the work. I gave myself a list and didn't move on until it felt natural:

1. **History.** Run five commands, then re-run the third with `Ctrl-R` and a fragment. Type `git` and press Up: only git history should show.
2. **Files.** `cat <Ctrl-T>`, pick `.zshrc`, and check bat highlights it. `Alt-C` to jump into a directory by fragment only.
3. **zoxide.** `cd ~/.fzf; cd /tmp; cd /etc; cd ~`, then `cd fzf` and `cd tmp`. Both should jump. `zoxide query -l` shows the ranking.
4. **eza.** `ll` (find the git column), `lt`, and `eza -la --sort=modified` to find the newest file.
5. **Completion.** `git ch<Tab>`, `cd /us<Tab><Tab>`, `kill <Tab>`.
6. **Recovery.** `echo garbage > ~/.zshrc; source ~/.zshrc`, see it break, `cp ~/.zshrc.bak ~/.zshrc`, and you're back. After doing this once, you trust the backup.

Done when Ctrl-R is the reflex and holding Up doesn't happen anymore.

## What's next

The editor. That's a separate post.
