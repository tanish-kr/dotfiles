export TERM='xterm-256color'
alias ls='ls --color=auto'
alias tree='tree --charset=C'

# tmux pbcopy alias
if [ `which pbcopy` ] && [ `which tmux` ] && [[ $OSTYPE != "drawin"* ]]; then
  alias tmcopy='tmux save-buffer - | pbcopy'
fi
