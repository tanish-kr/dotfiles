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
else
  alias ls='ls -F --color=auto'
fi

# alias gls='ls -laGF'
alias tree='tree --charset=C'

alias tmux="TERM=screen-256color-bce tmux"
alias spacemacs="emacs --insecure"
