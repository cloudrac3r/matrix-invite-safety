from functools import reduce
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

			# See if the users share any rooms.
			shared_room_ids = await self.api.run_db_interaction('matrix-invite-safety: get shared rooms', _db_get_shared_room_ids, target, sender)
			logger.info(f'   Debug: Users shared rooms: {shared_room_ids}')
			if len(shared_room_ids) == 0:
				logger.info('🔴 The users have no rooms in common')

			# See if the user has any active sessions. They won't know about the invite if they don't.
			access_token = await self.api.run_db_interaction('matrix-invite-safety: get access token', _db_get_access_token, target)
			if access_token is None:
				logger.info('🔴 The target has no active sessions to notice the invite with')
				return Codes.EXPIRED_ACCOUNT

			# Get room data for shared rooms, to see if the sender is a moderator+ in any of them.
			state = await self.api.http_client.post_json_get_json(
				'http://localhost:8008/_matrix/client/unstable/org.matrix.simplified_msc3575/sync',
				{
					'conn_id': 'matrix-invite-safety',
					'room_subscriptions': {
						room_id: {
							'required_state': [['m.room.power_levels', '*']],
							'timeline_limit': 0
						} for room_id in shared_room_ids
					}
				},
				{
					'Authorization': (f'Bearer {access_token}',)
				}
			)

			logger.info(f'   Debug: Shared rooms state response: {state}')

			for room_id, room in state['rooms'].items():
				power_levels = get_event(room['required_state'], 'm.room.power_levels', '')
				if power_levels is not None:
					power_level = get_key(power_levels, ['content', 'users', sender])
					if type(power_level) is int and power_level >= 50:
						logger.info(f'✅ The target is a moderator+ ({power_level=}) in a shared room ({room_id=}), so we trust them')
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

def _db_get_access_token(db, user_id) -> Optional[str]:
	db.execute('SELECT token FROM access_tokens WHERE user_id = ?', (user_id,))
	row = db.fetchone()
	if row is not None:
		return row[0]
	return None

def _db_get_shared_room_ids(db, local_user, remote_user) -> list[str]:
	db.execute('''
	select room_id from (
		select row_number() over (partition by room_memberships.room_id order by depth desc, stream_ordering desc) as row_number, room_memberships.room_id, membership
		from room_memberships
		inner join events using (event_id)
		where room_memberships.user_id = ?
		and room_memberships.room_id in (
			select room_id from local_current_membership
			where user_id = ?
			and membership = 'join'
		)
	) where row_number = 1 and membership = 'join';
	''', (remote_user, local_user,))
	rows = db.fetchall()
	return [row[0] for row in rows]
