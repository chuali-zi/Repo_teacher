from __future__ import annotations


class JsonOutputSidecarStripper:
    """Incrementally hides complete <json_output>...</json_output> blocks."""

    open_tag = "<json_output>"
    close_tag = "</json_output>"

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        self._buffer += chunk
        return self._drain(flush=False)

    def finish(self) -> list[str]:
        return self._drain(flush=True)

    def _drain(self, *, flush: bool) -> list[str]:
        visible_chunks: list[str] = []
        while self._buffer:
            open_index = self._buffer.find(self.open_tag)
            if open_index < 0:
                if flush:
                    visible_chunks.append(self._buffer)
                    self._buffer = ""
                else:
                    keep = min(len(self._buffer), len(self.open_tag) - 1)
                    emit_length = len(self._buffer) - keep
                    if emit_length <= 0:
                        break
                    visible_chunks.append(self._buffer[:emit_length])
                    self._buffer = self._buffer[emit_length:]
                break

            if open_index > 0:
                visible_chunks.append(self._buffer[:open_index])
                self._buffer = self._buffer[open_index:]
                continue

            close_index = self._buffer.find(self.close_tag, len(self.open_tag))
            if close_index < 0:
                if flush:
                    visible_chunks.append(self._buffer)
                    self._buffer = ""
                break

            self._buffer = self._buffer[close_index + len(self.close_tag) :]

        return [chunk for chunk in visible_chunks if chunk]
