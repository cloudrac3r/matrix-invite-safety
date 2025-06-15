# Matrix Invite Safety

A Synapse module that filters out room invites from unknown users.

Note that DM invites from unknown users are still allowed through.

## The Algorithm

The following algorithm is used to determine whether the sender is known. Once the user is determined to be trusted or not trusted, the algorithm terminates with that result.

1. If both people are on the same homeserver, it's TRUSTED.
1. If both people have an active DM already, it's TRUSTED.
1. If the invite is to DM, it's TRUSTED.
1. If the sender moderates a room that both people share, it's TRUSTED.
1. Otherwise, it's NOT trusted, because the people have no pre-existing relationship in Matrix data.

## Technical Notes

You need this Synapse patch to use this module: https://github.com/element-hq/synapse/pull/18241

Logs are stored in `/var/log/synapse/matrix-invite-safety.log`. If the folder doesn't exist, it will probably fail. You can change the log location by editing the code.

## Installation

Here's how I did it:

1. Clone the repo
1. `sudo python3 -m pip install .`
1. Add the following to Synapse homeserver.yaml, at the top level:
    ```
    modules:
      - module: matrix_invite_safety.InviteSafety
    ```
1. Restart Synapse. (Make sure it starts up okay. If it doesn't, find the error in the logs and troubleshoot it.)

## Code Changes

Please open a pull request if you have any changes regarding the installation process, algorithm, or anything else in this repo. I don't know anything about the Python ecosystem, so lots of things could probably be better here. Your help would be greatly appreciated!

1. Make your code change
1. Type check: I used `mypy invites.py`
1. Install the new version: `sudo python3 -m pip install .`
1. Restart Synapse and try it out.

If you are an employee of New Vector Ltd, please contact me @cadence:cadence.moe before contributing.

## Resources

May be useful as reference or examples.

* info about modules https://mau.dev/maunium/synapse/-/blob/21d6636b74bf3482e3bab985367fb9dee106e0f4/docs/modules.md
* module API ""reference"" https://github.com/element-hq/synapse/blob/master/synapse/module_api/__init__.py
* federation `on_invite_request` https://github.com/element-hq/synapse/blob/f56670515bc402e13ee0bb2dd99ceb6e2ea8ba7d/synapse/federation/transport/server/federation.py#L519
* `post_json_get_json` https://github.com/element-hq/synapse/blob/e4ca593eb6c3ddd4ee98091553df5f92344fc587/synapse/http/client.py#L513
* https://github.com/matrix-org/matrix-spec-proposals/blob/erikj/sss/proposals/4186-simplified-sliding-sync.md
* https://github.com/lovelaced/synapse-mayinvite/
* https://github.com/maunium/synapse-http-antispam
* https://github.com/t2bot/synapse-simple-antispam
