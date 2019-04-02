# coding: utf-8
# -*- mode: ruby -*-
# vi: set ft=ruby :

require 'pry'
require 'pry-theme'
require 'highline'
require 'logger'

# pry-theme
Pry.config.theme = "monokai"

# prompt setting
Pry.config.prompt = proc do |obj, level, _|
  prompt = ""
  prompt << "#{Rails.version}@" if defined?(Rails)
  prompt << "#{RUBY_VERSION}"
  "#{prompt} (#{obj})> "
end

# Reformat Exception
Pry.config.exception_handler = proc do |output, exception, _|
  output.puts "\e[31m#{exception.class}: #{exception.message}"
  output.puts "from #{exception.backtrace.first}\e[0m"
end

# pry-byebug alias
if defined?(PryByebug)
  Pry.commands.alias_command 'c',  'continue'
  Pry.commands.alias_command 's',  'step'
  Pry.commands.alias_command 'n',  'next'
  Pry.commands.alias_command 'f',  'finish'
  Pry.commands.alias_command 'ss', 'show-source'
end

# Oter global alias
Pry.commands.alias_command 'q', 'exit'

# Print (current) working directory
def pwd
  %x{pwd}.rstrip
end

# Pist all installed gems
def glist
  system('gem list')
end

# List only filenames, one per line, in alpha order
def lf
  system('ls -laGF')
end

# List only directories
def ld
  system('ls -laGF | egrep "^d"')
end

# Display RAILS_ENV
def rails_env
  puts ENV["RAILS_ENV"]
end

# Display git status
def g_sts
  system('git status -s')
end

# Display git log
def g_comment
  system('git log --oneline')
end

def g_diff
  system('git diff')
end

# Display database info
def db_config
  ApplicationRecord.connection_config
end

def routes
  system('rake routes')
end

def log(message, level = :info, title = nil)
  @logger = Logger.new("log/pry.log")
  title ||= message.class
  @logger.send(level.to_sym, title) { message }
end