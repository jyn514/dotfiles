#!/bin/sh
kill -PIPE "$$"
printf 'survived\n'
