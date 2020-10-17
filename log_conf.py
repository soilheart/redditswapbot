import sys, os
from configparser import SafeConfigParser
import logging
import mySQLHandler

# load config file
containing_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
cfg_file = SafeConfigParser()
path_to_cfg = os.path.join(containing_dir, 'config.cfg')
cfg_file.read(path_to_cfg)
logging_dest = cfg_file.get('logging','dest')
sentry = cfg_file.get('logging','sentry')

try:
    import sentry_sdk
except ImportError:
    # sentry_sdk not installed, skip sentry even though config exists
    sentry = ""

mysql_hostname = cfg_file.get('mysql', 'hostname')
mysql_username = cfg_file.get('mysql', 'username')
mysql_password = cfg_file.get('mysql', 'password')
mysql_database = cfg_file.get('mysql', 'database')

class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances.keys():
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
            if sentry and not "disable_sentry" in kwargs:
                sentry_sdk.init(sentry)

        return cls._instances[cls]

class LoggerManager(object, metaclass=Singleton):
    _loggers = {}

    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def getLogger(name=None, enable_sentry=True):
        #configure logging
        LoggerManager._loggers[name] = logging.getLogger(name)
        LoggerManager._loggers[name].setLevel(logging.INFO)

        if logging_dest == 'mysql':
            db = {'host':mysql_hostname, 'port':3306, 'dbuser':mysql_username, 'dbpassword':mysql_password, 'dbname':mysql_database}

            sqlh = mySQLHandler.mySQLHandler(db)
            LoggerManager._loggers[name].addHandler(sqlh)
        else:
            fileh = logging.FileHandler('actions.log')
            fileh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(module)s - %(message)s'))
            LoggerManager._loggers[name].addHandler(fileh)

        requests_log = logging.getLogger("requests")
        requests_log.setLevel(logging.WARNING)

        return LoggerManager._loggers[name]
