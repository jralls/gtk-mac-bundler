import sys

from .project import *
from .bundler import *

def main(argv):
    if len(argv) != 1:
        print("Usage: main.py <bundle description file>")
        sys.exit(2)

    if not os.path.exists(argv[0]):
        print("File %s does not exist" % (argv[0]))
        sys.exit(2)

    project = Project(argv[0])
    bundler = Bundler(project)
    #try:
    bundler.run()
    #except Exception as err:
     #   print("Bundler encountered an error %s" % str(err))

if __name__ == '__main__':
    main(sys.argv[1:])
