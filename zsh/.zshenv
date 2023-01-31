export TERM='xterm-256color'
# alias ls='ls --color=auto'

# tmux pbcopy alias
if [[ `which pbcopy` ]] && [[ `which tmux` ]]; then
  if [ "$(uname)" = 'Darwin' ]; then
    alias tmcopy='tmux save-buffer - | pbcopy'
  else
    alias tmcopy='tmux save-buffer - | srv-pbcopy'
  fi
fi

if [ "$(uname)" = 'Darwin' ]; then
  alias ls='ls -GF'
  alias ll='ls -lahtr'
  if [[ `which gsed` ]]; then
    alias sed='gsed'
  fi
else
  alias ls='ls -F --color=auto'
fi


# alias gls='ls -laGF'
alias tree='tree --charset=C'

alias tmux="TERM=screen-256color-bce tmux"
alias spacemacs="emacs --insecure"

# before intall jman @see http://tukaikta.blog135.fc2.com/blog-entry-224.html
alias man='env LANG=C man'
alias jman='env LANG=ja_JP.UTF-8 man'
alias nonmacs="emacs -q"

if [ -e "/Applications/MacVim.app/Contents/MacOS/Vim" ]; then
  alias vim='/Applications/MacVim.app/Contents/MacOS/Vim'
fi

alias chrome="/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome"
alias chrome-canary="/Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary"
alias chromium="/Applications/Chromium.app/Contents/MacOS/Chromium"
