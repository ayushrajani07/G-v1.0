from typing import Callable, Dict, Any, Iterable
import queue
import threading


class StreamIngestor:
    def __init__(self, emitter: Callable[[Dict[str, Any]], None]):
        self._emitter = emitter
        self._q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        if not self._t.is_alive():
            self._t.start()

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=2)

    def enqueue(self, item: Dict[str, Any]) -> None:
        self._q.put(item)

    def bulk_enqueue(self, items: Iterable[Dict[str, Any]]) -> None:
        for it in items:
            self._q.put(it)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._emitter(item)
            finally:
                self._q.task_done()
