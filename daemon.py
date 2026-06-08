import time
import traceback

from main import main


CHECK_INTERVAL = 60


def run_daemon():

    print("\n==============================")
    print("EMAIL AGENT DAEMON STARTED")
    print("==============================\n")

    while True:

        try:

            print("\nChecking inbox...\n")

            main()

            print(f"\nSleeping for {CHECK_INTERVAL} seconds...\n")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:

            print("\nDAEMON ERROR:\n")

            print(str(e))

            traceback.print_exc()

            print("\nRetrying in 30 seconds...\n")

            time.sleep(30)


if __name__ == "__main__":

    run_daemon()
