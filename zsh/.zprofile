# PATHの順番に気をつけないと行けないのでこちらに設定
PATH=$HOME/bin:$PATH

# anyenvがあればそれだけでいい
if [ -e $HOME/.anyenv ]; then
  export PATH="$HOME/.anyenv/bin:$PATH"
  eval "$(anyenv init - zsh)"
  if [ -e $HOME/.anyenv/envs/pyenv/plugins/pyenv-virtualenv ]; then
    eval "$(pyenv virtualenv-init -)"
  fi
  if [ -e $HOME/.anyenv/envs/ndenv ]; then
    eval "$(ndenv init -)"
  fi
else
  if [ -e $HOME/.rbenv ]; then
    export PATH="$HOME/.rbenv/bin:$PATH"
    eval "$(rbenv init -)"
  fi
fi

# go path
export GOPATH=$HOME/.go
export PATH=$GOPATH/bin:$PATH

# for direnv
if type "direnv" > /dev/null 2>&1; then
  export EDITOR=vim
  eval "$(direnv hook zsh)"
fi

# vscode cli tools
if [ "$(uname)" = 'Darwin' ] && [ -e "/Applications/Visual Studio Code.app" ]; then
  export PATH="/Applications/Visual Studio Code.app/Contents/Resources/app/bin:$PATH"
fi
