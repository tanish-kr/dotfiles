export TERM='xterm-256color'
# alias ls='ls --color=auto'

alias tree='tree --charset=C'

# tmux pbcopy alias
if [[ `which pbcopy` ]] && [[ `which tmux` ]]; then
  alias tmcopy='tmux save-buffer - | pbcopy'
fi

alias gls='ls -laGF'
alias tree='tree --charset=C'

alias tmux="TERM=screen-256color-bce tmux"
alias spacemacs="emacs --insecure"

# tmux ssh-agent
# agent="$HOME/tmp/ssh-agent-$USER"
# if [ -S "$SSH_AUTH_SOCK" ]; then
#   case $SSH_AUTH_SOCK in
#     /tmp/*/agent.[0-9]*)
#       ln -snf "$SSH_AUTH_SOCK" $agent && export SSH_AUTH_SOCK=$agent
#   esac
# elif [ -S $agent ]; then
#   export SSH_AUTH_SOCK=$agent
# else
#   echo "no ssh-agent"
# fi
