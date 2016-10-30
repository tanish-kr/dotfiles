if [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi

PATH=$HOME/bin:$PATH
export PATH="$HOME/.rbenv/bin:$PATH"
eval "$(rbenv init -)"

export TERM='xterm-256color'
# alias ls='ls --color=auto'
alias gls='ls -laGF'
alias tree='tree --charset=C'

alias tmux="TERM=screen-256color-bce tmux"
