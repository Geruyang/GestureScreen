"""Session-scoped staging over the legacy capture journal; retained data never auto-deletes."""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import shutil
import threading
import time
import uuid

from capture_server import (ApiError, CaptureStore, ID_RE, LABELS, PREPROCESSING,
                            atomic_json, utc_now)


class DataDirectoryLock:
    """One service owns a capture directory, even across standalone EXE processes."""
    def __init__(self, root):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.stream = (root / '.studio.lock').open('a+b')
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b'0')
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise RuntimeError('此采集目录已被另一服务使用。')

    def close(self):
        if not self.stream.closed:
            self.stream.close()


class ManagedCaptureStore(CaptureStore):
    LEASE_SECONDS = 15.0
    TEMP_MARKER = 'gesture-studio-temporary-v1'

    def __init__(self, root, *, max_frames=10000, clock=time.monotonic, recognition=False, raw_capture_only=False):
        self.raw_capture_only = raw_capture_only
        self.workspace_owner = None
        self.expired_owner = None
        self.workspace_until = 0.0
        self.view_session = None
        self.viewers = {}
        self.recognizer = None
        self.recognition_error = ''
        self.model_info = None
        self.recognition_result = None
        self._stopped = threading.Event()
        self._model_event = threading.Event()
        self._model_latest = None
        super().__init__(root, max_frames=max_frames, clock=clock)
        self._janitor = threading.Thread(target=self._lease_loop, name='session-lease', daemon=True)
        self._janitor.start()
        if recognition:
            self._model_thread = threading.Thread(target=self._recognition_loop, name='gesture-model', daemon=True)
            self._model_thread.start()

    def _load(self):
        # A service restart alone never deletes data. The next explicit window
        # open/new/close clears marked staging according to the UI contract.
        super()._load()

    def _remove_temporary_folder(self, session_id):
        if not isinstance(session_id, str) or not ID_RE.fullmatch(session_id):
            raise ValueError('invalid staging session ID')
        expected_parent = (self.root / 'sessions').resolve()
        folder = self.root / 'sessions' / session_id
        if folder.is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(folder)):
            raise ValueError('refusing a redirected staging directory')
        resolved = folder.resolve()
        if resolved.parent != expected_parent or not resolved.is_relative_to(self.root):
            raise ValueError('staging path escaped capture directory')
        metadata = json.loads((resolved / 'session.json').read_text(encoding='utf-8'))
        if metadata.get('session_id') != session_id or metadata.get('lifecycle') != self.TEMP_MARKER:
            raise ValueError('refusing to delete retained or unmarked data')
        shutil.rmtree(resolved)

    def _bump(self):
        super()._bump()
        self.recognition_result = None
        self._model_latest = None

    def _clear_temporary(self):
        """Called under the store lock: invalidate in-flight tickets before removal."""
        self.active = False
        self._cancel_auto_timer()
        self._bump()
        targets = [key for key, row in self.sessions.items() if row.get('lifecycle') == self.TEMP_MARKER]
        for key in targets:
            self._remove_temporary_folder(key)
        removed = {key for key, row in self.records.items() if row['session'] in targets}
        self.records = {key: row for key, row in self.records.items() if key not in removed}
        self.order = [key for key in self.order if key not in removed]
        self.identities = {key: value for key, value in self.identities.items() if value not in removed}
        self.hashes = {key: value for key, value in self.hashes.items() if value not in removed}
        self.clips = {key: row for key, row in self.clips.items() if row.get('session') not in targets}
        self.pending_clips = {key: row for key, row in self.pending_clips.items() if row.get('session_id') not in targets}
        for key in targets:
            self.sessions.pop(key, None)
        self.current = None
        self.active_clip = None
        self.view_session = None

    def _expire(self):
        now = self.clock()
        self.viewers = {owner: expiry for owner, expiry in self.viewers.items() if expiry > now}
        self.preview_until = max(self.viewers.values(), default=0.0)
        if self.workspace_owner and self.workspace_until <= now:
            # Background browser throttling, sleep or network interruption must
            # not delete an unfinished recording. Freeze until open/new/close.
            if self.active_clip is not None:
                self.clip_action({'action':'stop'})
            self.active = False
            self._bump()
            self.expired_owner = self.workspace_owner
            self.workspace_owner = None
            self.workspace_until = 0.0

    def _lease_loop(self):
        while not self._stopped.wait(1):
            try:
                with self.lock:
                    self._expire()
            except (OSError, ValueError) as error:
                with self.lock:
                    self.last_error = f'临时会话清理失败：{error}'

    def require_owner(self, data):
        owner = data.get('owner')
        with self.lock:
            self._expire()
            if not owner or owner != self.workspace_owner:
                raise ApiError(409, 'workspace_owner', '当前窗口没有采集控制权，请关闭其他采集窗口后重试。')
            self.workspace_until = self.clock() + self.LEASE_SECONDS

    def workspace_action(self, data):
        owner, action = data.get('owner'), data.get('action')
        if not isinstance(owner, str) or not ID_RE.fullmatch(owner) or action not in ('open', 'keep', 'close'):
            raise ApiError(400, 'workspace_request', '无效会话窗口请求。')
        with self.lock:
            self._expire()
            if action == 'close':
                self.viewers.pop(owner, None)
                if self.workspace_owner == owner or (self.workspace_owner is None and self.expired_owner == owner):
                    self._clear_temporary()
                    self.workspace_owner = None
                    self.expired_owner = None
                    self.workspace_until = 0.0
            elif action == 'open':
                if self.workspace_owner is None:
                    if owner != self.expired_owner:
                        self._clear_temporary()
                    self.workspace_owner = owner
                    self.expired_owner = None
                if self.workspace_owner == owner:
                    self.workspace_until = self.clock() + self.LEASE_SECONDS
            elif owner == self.workspace_owner or (self.workspace_owner is None and owner == self.expired_owner):
                self.workspace_owner = owner
                self.expired_owner = None
                self.workspace_until = self.clock() + self.LEASE_SECONDS
            self.preview_until = max(self.viewers.values(), default=0.0)
            return dict(ok=True, editable=self.workspace_owner == owner, **self.state())

    def preview_action(self, data):
        owner, action = data.get('owner'), data.get('action')
        if not isinstance(owner, str) or not ID_RE.fullmatch(owner) or action not in ('start', 'keep', 'stop'):
            raise ApiError(400, 'preview_request', '无效观察请求。')
        with self.lock:
            self._expire()
            was_live = self.preview_until > self.clock()
            if action == 'stop':
                self.viewers.pop(owner, None)
            else:
                if action == 'keep' and owner not in self.viewers:
                    raise ApiError(409, 'preview_expired', '观察已过期，请重新连接。')
                self.viewers[owner] = self.clock() + self.LEASE_SECONDS
            self.preview_until = max(self.viewers.values(), default=0.0)
            if not self.active and was_live != (self.preview_until > self.clock()):
                self._bump()
            return self.preview_status()

    def session_action(self, data):
        with self.lock:
            action = data.get('action')
            if action == 'new':
                # Validate before clearing: a malformed request must never discard a session.
                if data.get('split') not in ('train', 'validation', 'calibration', 'test'):
                    raise ApiError(400, 'invalid_split', '请选择合法的会话用途。')
                for key in ('name', 'sensor_profile', 'exposure_profile'):
                    value = data.get(key, '')
                    if not isinstance(value, str) or not value.strip() or len(value) > 160 or any(ord(c) < 32 for c in value):
                        raise ApiError(400, 'session_metadata', f'{key} 格式无效。')
                session_id = uuid.uuid4().hex
                session = dict(session_id=session_id, split=data['split'], created_at=utc_now(),
                               lifecycle=self.TEMP_MARKER,
                               **{k:data[k].strip() for k in ('name', 'sensor_profile', 'exposure_profile')})
                # Publish only a fully initialized directory. A disk failure or
                # crash before rename leaves a hidden, loader-ignored staging
                # directory, never an invalid UUID session that blocks startup.
                staging = self.path(f'sessions/.creating-{session_id}')
                staging.mkdir(parents=True, exist_ok=False)
                atomic_json(staging / 'session.json', session)
                (staging / 'frames').mkdir()
                (staging / 'clips').mkdir()
                staging.rename(self.path(f'sessions/{session_id}'))
                self._clear_temporary()
                self.sessions[session_id] = self.current = session
                self.view_session = session_id
            elif action in ('save', 'stop'):
                if self.current is None:
                    raise ApiError(409, 'no_session', '请先新建会话。')
                current_id = self.current['session_id']
                pending_here = any(row.get('session_id') == current_id for row in self.pending_clips.values())
                if self.active_clip is not None or pending_here or self.pending_recordings:
                    raise ApiError(409, 'clip_open', '请先停止录制并完成片段标注。')
                saved = dict(self.current, lifecycle='retained', ended_at=utc_now())
                saved.pop('workspace_owner', None)
                atomic_json(self.path(f'sessions/{current_id}/session.json'), saved)
                self.sessions[current_id] = saved
                self.current = None
                self.view_session = current_id
                self._bump()
            else:
                raise ApiError(400, 'invalid_action', '未知会话操作。')
            return self.state()

    def clip_action(self, data):
        with self.lock:
            historical = {k:v for k,v in self.pending_clips.items() if v.get('session_id') != self.view_session}
            self.pending_clips = {k:v for k,v in self.pending_clips.items() if k not in historical}
            try:
                return super().clip_action(data)
            finally:
                self.pending_clips.update(historical)

    def annotate(self, data):
        with self.lock:
            if self.raw_capture_only:
                raise ApiError(409, 'raw_capture_only', '本工具仅保留采集素材，训练资格请在外部清洗工具中确定。')
            row = self.records.get(data.get('record_id'))
            if row is None or row['session'] != self.view_session or self.current is None:
                raise ApiError(409, 'history_read_only', '历史已保存；只能修改当前临时会话。')
            return super().annotate(data)

    def _visible_ids(self, scope='current'):
        if scope == 'history':
            return [key for key in self.order if self.sessions[self.records[key]['session']].get('lifecycle') != self.TEMP_MARKER]
        return [key for key in self.order if self.records[key]['session'] == self.view_session]

    def state(self):
        with self.lock:
            result = super().state()
            ids = self._visible_ids()
            counts = Counter(self.records[key]['label'] for key in ids
                             if self.records[key]['label'] in LABELS and not self.records[key].get('excluded'))
            history_ids = self._visible_ids('history')
            result.update(total=len(ids), included=sum(counts.values()), counts=counts,
                          recent=[dict(self.records[key]) for key in reversed(ids[-30:])],
                          pending_clips=[self._clip_summary(row) for row in self.pending_clips.values()
                                         if row.get('session_id') == self.view_session],
                          recent_clips=[self._clip_summary(row) for row in sorted(self.clips.values(), key=lambda r:r['completed_at'], reverse=True)
                                        if row.get('session') == self.view_session][:12],
                          workspace_busy=self.workspace_owner is not None, view_session=self.view_session,
                          session_saved=bool(self.view_session and self.sessions.get(self.view_session, {}).get('lifecycle') != self.TEMP_MARKER),
                          history_total=len(history_ids),
                          history_included=sum(self.records[k]['label'] in LABELS and not self.records[k].get('excluded') for k in history_ids),
                          capabilities=['live_preview_v1', 'session_workspace_v2', 'model_recognition_v1', 'clip_auto_finish_v1'],
                          model=self.model_info, model_error=self.recognition_error)
            if self.raw_capture_only:
                result['capabilities'].append('raw_capture_v1')
            result.update(raw_capture_only=self.raw_capture_only, captured_total=len(ids),
                          exportable_total=sum(len(c.get('record_ids', [])) for c in self.clips.values()
                                               if c.get('session') == self.view_session),
                          captured_counts=Counter(self.records[key]['label'] for key in ids
                                                 if self.records[key]['label'] in LABELS))
            return result

    def page(self, offset, limit, scope='current'):
        if scope not in ('current', 'history') or not 0 <= offset <= 100000 or not 1 <= limit <= 50:
            raise ApiError(400, 'page_query', '分页参数无效。')
        with self.lock:
            ids = list(reversed(self._visible_ids(scope)))
            return dict(total=len(ids), samples=[dict(self.records[key]) for key in ids[offset:offset+limit]])

    def history(self):
        with self.lock:
            return dict(total=len(self._visible_ids('history')),
                        clips=[self._clip_summary(row) for row in sorted(self.clips.values(), key=lambda r:r['completed_at'], reverse=True)
                               if self.sessions[row['session']].get('lifecycle') != self.TEMP_MARKER],
                        sessions=[row for row in self.sessions.values() if row.get('lifecycle') != self.TEMP_MARKER])

    def export(self, scope='current'):
        with self.lock:
            if scope not in ('current', 'history'):
                raise ApiError(400, 'export_scope', '无效导出范围。')
            if scope == 'current' and (not self.view_session or self.current is not None):
                raise ApiError(409, 'save_first', '请先保存到历史，再导出清单。')
            if self.active or self.pending_recordings or any(row.get('session_id') == self.view_session for row in self.pending_clips.values()):
                raise ApiError(409, 'capture_active', '请先停止片段并完成标注。')
            if self.raw_capture_only:
                # Export every committed image, including identical pixels and
                # unreviewed/previously discarded material. Source history stays
                # untouched; this export is explicitly not a training approval.
                rows = [dict(self.records[key], excluded=True,
                             source_training_excluded=self.records[key].get('excluded', True),
                             review_status='unreviewed') for key in self._visible_ids(scope)]
            else:
                rows = [dict(self.records[key]) for key in self._visible_ids(scope)
                        if self.records[key]['label'] in LABELS and not self.records[key].get('excluded')
                        and self.records[key].get('training_duplicate_of') is None]
            sessions = {row['session'] for row in rows}
            clips = [dict(row) for row in self.clips.values() if row.get('session') in sessions and (self.raw_capture_only or row.get('status') == 'labeled')]
            manifest = dict(schema_version=1, preprocessing=PREPROCESSING, exported_at=utc_now(), samples=rows, clips=clips,
                            note='已保存数据；人工标签独立于模型预测。')
            if self.raw_capture_only:
                manifest.update(purpose='raw_capture_unreviewed', training_ready=False,
                                note='完整采集素材，类别仅为录制意图；未判断画面是否适合训练，请在外部清洗后建立训练清单。')
            export_id = uuid.uuid4().hex
            target = self.path(f'dataset_manifest_{export_id}.json')
            atomic_json(target, manifest)
            return dict(ok=True, sample_count=len(rows), manifest=str(target), download=f'/export/{export_id}.json', purpose=manifest.get('purpose', 'training_dataset'))

    def commit(self, ticket, raw):
        result = super().commit(ticket, raw)
        with self.lock:
            if ticket['epoch'] == self.epoch:
                self._model_latest = (raw, ticket['frame_id'], self.epoch, self.preview_sequence, self.preview_received)
                self._model_event.set()
        return result

    def _recognition_loop(self):
        try:
            from model_runtime import GestureModel
            self.recognizer = GestureModel()
            self.model_info = self.recognizer.identity
        except Exception as error:
            self.recognition_error = f'模型未就绪：{error}'
            return
        while not self._stopped.is_set():
            self._model_event.wait(0.25)
            self._model_event.clear()
            with self.lock:
                item, self._model_latest = self._model_latest, None
            if item is None:
                continue
            raw, frame_id, epoch, sequence, received = item
            try:
                result = self.recognizer.predict(raw, frame_id)
                result.update(epoch=epoch, sequence=sequence, received=received)
                with self.lock:
                    if epoch == self.epoch and sequence == self.preview_sequence:
                        self.recognition_result = result
                        self.recognition_error = ''
            except Exception as error:
                with self.lock:
                    self.recognition_result = None
                    self.recognition_error = f'识别暂不可用：{error}'

    def live(self):
        with self.lock:
            row = self.recognition_result
            valid = row and row['epoch'] == self.epoch and row['sequence'] == self.preview_sequence and self.clock() - row['received'] <= 0.3
            return dict(epoch=self.epoch, preview=self.preview_status(),
                        recognition=dict({k:v for k,v in row.items() if k != 'received'}, age_ms=int((self.clock()-row['received'])*1000)) if valid else None,
                        model_error=self.recognition_error)

    def close(self):
        self._stopped.set()
        self._model_event.set()
        self._janitor.join(timeout=2)
        if hasattr(self, '_model_thread'):
            self._model_thread.join(timeout=5)
        with self.lock:
            self.viewers.clear()
            self.preview_until = 0
            # A service shutdown is not an explicit user discard. In particular,
            # idle exit after a sleeping/lost window must preserve its staging.
            if self.active_clip is not None:
                self.clip_action({'action': 'stop'})
            self.active = False
            self._cancel_auto_timer()
            self._bump()
            self.workspace_owner = None
