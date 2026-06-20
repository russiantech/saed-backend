from django.core.management.commands.runserver import Command as RunserverCommand

class Command(RunserverCommand):
    default_addr = '127.0.0.1'
    default_port = '8002'