export function readerFollowsTranscript(viewport, root) {
  return viewport.scrollY + viewport.innerHeight >= root.scrollHeight - 1;
}

export function appendLiveMessage(stream, item, follow) {
  stream.append(item);
  if (follow) item.scrollIntoView({ block: 'nearest' });
}

export function participantLabel(messageSide, ownSide, mineName, theirName) {
  return messageSide === ownSide ? mineName || 'your side' : theirName || 'their side';
}
