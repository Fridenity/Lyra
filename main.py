import os
import dotenv

dotenv.load_dotenv()

from src import bot, activity


if __name__ == '__main__':
    if os.name != 'nt':
        import uvloop

        uvloop.install()

    bot.run(activity=activity)
