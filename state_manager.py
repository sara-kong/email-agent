import json
import os

STATE_FILE = "index_state.json"


def load_state():

    if not os.path.exists(STATE_FILE):

        return {
            "next_page_token": None
        }

    with open(STATE_FILE, "r") as f:

        return json.load(f)


def save_state(next_page_token):

    state = {
        "next_page_token": next_page_token
    }

    with open(STATE_FILE, "w") as f:

        json.dump(state, f)
