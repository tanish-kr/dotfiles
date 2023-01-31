# PATHの順番に気をつけないと行けないのでこちらに設定
PATH=$HOME/bin:$PATH


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
