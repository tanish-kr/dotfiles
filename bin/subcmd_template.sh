#!/bin/sh
#
# chkconfig: - 85 15
# description: description
# processname: processname
# . /etc/rc.d/init.d/function

# set variables
PROCESS_NAME="process"
USER="develop"

start(){
  if status; then
    echo "$PROCESS_NAME already started"
    exit 1
  fi
  echo "Starting $PROCESS_NAME..."
  
  # TODO: start command
}

stop(){
  if ! status; then
    echo "$PROCESS_NAME not started"
    exit 1
  fi
  echo "Stopping $PROCESS_NAME..."
  
  # TODO: stop command
}

force_stop(){
  if ! status; then
    echo "$PROCESS_NAME not started"
    exit 1
  fi
  echo "Stopping $PROCESS_NAME..."
  
  # TODO: force stop command
}

reload(){
  if ! status; then
    start
    exit 0
  fi
  echo "Reloading $PROCESS_NAME..."
  
  # TODO: stop command
}

restart(){
  if ! status; then
    start
    exit 0
  fi
  echo "Restarting $PROCESS_NAME..."
  
  # TODO: restart command
}

status(){
  if [ -e $PID ]; then
    true
  else
    false
  fi
}

help(){
  echo "Usage: $0 <start|stop|force_stop|reload|restart|status>"
  echo "  - start:        Start $PROCESS_NAME"
  echo "  - stop:         Stop $PROCESS_NAME"
  echo "  - force_stop:   "
  echo "  - reload:       Reload $PROCESS_NAME"
  echo "  - restart:      Restart $PROCESS_NAME"
  echo "  - status:       $PROCESS_NAME process status."
}

case $1 in
  start)
    start
    ;;
  stop)
    stop
    ;;
  force_stop)
    force_stop
    ;;
  reload)
    reload
    ;;
  restart)
    restart
    ;;
  status)
    if status; then
      echo "$PROCESS_NAME started"
    else
      echo "$PROCESS_NAME not started"
    fi
    ;;
  help)
    help
    exit 0
    ;;
  *)
    help
    exit 1
    ;;
esac