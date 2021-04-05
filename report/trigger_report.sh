DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd $DIR/../
export DJANGO_SETTINGS_MODULE=settings.production  # 否则获取不到 telegram bot token..
pipenv run python manage.py trigger_report
