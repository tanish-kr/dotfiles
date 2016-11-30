if [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi

PATH=$HOME/bin:$PATH
export PATH="$HOME/.rbenv/bin:$PATH"
eval "$(rbenv init -)"

export TERM='xterm-256color'
alias ls='ls --color=auto'
alias tree='tree --charset=C'

# tmux ssh-agent
agent="$HOME/tmp/ssh-agent-$USER"
if [ -S "$SSH_AUTH_SOCK" ]; then
  case $SSH_AUTH_SOCK in
    /tmp/*/agent.[0-9]*)
      ln -snf "$SSH_AUTH_SOCK" $agent && export SSH_AUTH_SOCK=$agent
  esac
elif [ -S $agent ]; then
  export SSH_AUTH_SOCK=$agent
else
  echo "no ssh-agent"
fi
