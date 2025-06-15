from functools import reduce
import json
import logging
import pathlib
import traceback
logger = logging.getLogger(__name__)

from synapse.api.errors import SynapseError, Codes
from synapse.events import EventBase
from synapse.module_api import ModuleApi, NOT_SPAM
from typing import Dict, Optional

class InviteSafety:
	def __init__(self, config: dict, api: ModuleApi):
		self.api = api

		api.register_spam_checker_callbacks(
			federated_user_may_invite=self.federated_user_may_invite
		)

		log_file = '/var/log/synapse/matrix-invite-safety.log'
		fileHandler = logging.FileHandler(log_file)
		fileHandler.setLevel(logging.DEBUG)
		logger.addHandler(fileHandler)
		logger.info('Started')

	async def federated_user_may_invite(self, event: EventBase):
		try:
			sender = event.sender
			target = event.state_key
			logger.info(f'👀 Detected invite from {sender} to {target} for {event.room_id}')

			# We trust senders on our closed registration homeserver.
			if self.api.is_mine(sender):
				logger.info('✅ Sender is from this homeserver, so we trust them')
				return NOT_SPAM

			# Get account data for target user, to see whether they already have a DM with the sender.
			direct = await self.api.account_data_manager.get_global(target, 'm.direct')
			# logger.info(f'm.direct account data of {target}: {direct}')
			if direct is not None and sender in direct and len(direct[sender]) > 0:
				logger.info('✅ The target has an active DM with the sender, so we trust them')
				return NOT_SPAM
			logger.info('   The target does not have an active DM with the sender')

			invite_room_state = event.unsigned.get('invite_room_state')
			room_name_event = get_event(invite_room_state, 'm.room.name', '')
			is_direct_event = get_event(invite_room_state, 'm.room.member', target)
			is_direct = bool(get_key(is_direct_event, ['content', 'is_direct']))
			logger.info(f'   Debug: Invite room state: {invite_room_state}')

			# Allow DM invites
			if room_name_event is None:
				logger.info(f'✅ Is a new direct chat ({is_direct=}), this is acceptable')
				return NOT_SPAM

			# See if sender is a moderator+ in any rooms shared between the users.
			power_level_events = await self.api.run_db_interaction('matrix-invite-safety: get shared room power levels', _db_get_shared_room_remote_user_power_levels, target, sender)
			for power_level_event_json in power_level_events:
				power_level_event = json.loads(power_level_event_json)
				power_level = get_key(power_level_event, ['content', 'users', sender])
				if type(power_level) is int and power_level >= 50:
					logger.info(f'✅ The target is a moderator+ ({power_level=}) in a shared room ({event["room_id"]=}), so we trust them')
					return NOT_SPAM

			# Don't allow invites to unknown shared rooms from unknown senders
			logger.info(f'🔴 Is a non-DM room from an untrusted person. Room name: {get_key(room_name_event, ['content', 'name'])}')
			return Codes.FORBIDDEN

		except Exception:
			logger.error(f'Exception: {traceback.format_exc()}')
			return NOT_SPAM # fail open

def get_event(events, type: str, state_key: Optional[str] = None):
	return next((e for e in events if e['type'] == type and (state_key is None or e['state_key'] == state_key)), None)

def get_key(dictionary: dict, keys: list[str]):
	try:
		return reduce(lambda d, key: d[key], keys, dictionary)
	except Exception:
		return None

def _db_get_shared_room_remote_user_power_levels(db, local_user, remote_user) -> list[str]:
	db.execute('''
		select json
		from current_state_events
		inner join event_json using (event_id)
		where current_state_events.room_id in (
			select room_id
			from (
				select row_number() over (partition by room_memberships.room_id order by depth desc, stream_ordering desc) as row_number, room_memberships.room_id, membership
				from room_memberships
				inner join events using (event_id)
				where room_memberships.user_id = ?
				and room_memberships.room_id in (
					select room_id from local_current_membership
					where user_id = ?
					and membership = 'join'
				)
			)
			where row_number = 1
			and membership = 'join'
		)
		and type = 'm.room.power_levels'
		and state_key = ''
	''', (remote_user, local_user,))
	rows = db.fetchall()
	return [row[0] for row in rows]
