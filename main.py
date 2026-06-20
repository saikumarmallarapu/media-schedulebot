import os
import sys

from django.core.management import execute_from_command_line


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "media_schedulebot.settings")
    args = ["manage.py", *sys.argv[1:]]
    if len(args) == 1:
        args.append("runserver")
    execute_from_command_line(args)


if __name__ == "__main__":
    main()
