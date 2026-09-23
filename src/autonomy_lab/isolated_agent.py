"""Agent entry point: only its checkpoint volume and a framed tool/model channel."""

import sys
from pathlib import Path

from autonomy_lab.agent import run_agent
from autonomy_lab.rpc import RemoteError, read_frame, write_frame


class Channel:
    def __init__(self):
        self.sequence = 0

    def call(self, method, **arguments):
        self.sequence += 1
        write_frame(sys.stdout.buffer, {"id": self.sequence, "method": method, "arguments": arguments})
        response = read_frame(sys.stdin.buffer)
        if response.get("id") != self.sequence:
            raise ValueError("RPC response identity mismatch")
        if "error" in response:
            raise RemoteError(response["error"])
        return response["result"]


class Model:
    def __init__(self, channel, model):
        self.channel, self.model = channel, model

    def count_tokens(self, contents, system_instruction, declarations):
        return self.channel.call("count_tokens", contents=contents, system_instruction=system_instruction,
                                 declarations=declarations)

    def generate(self, contents, system_instruction, declarations, max_output_tokens):
        return self.channel.call("generate", contents=contents, system_instruction=system_instruction,
                                 declarations=declarations, max_output_tokens=max_output_tokens)


class Toolbox:
    def __init__(self, channel, config):
        self.channel = channel
        self.run_id = config["run_id"]
        self._declarations = config["declarations"]
        self.terminal = config["terminal"]

    def declarations(self):
        return self._declarations

    def call(self, name, args):
        response = self.channel.call("tool", name=name, args=args)
        self.terminal = response["terminal"]
        return response["observation"]


def main():
    config = read_frame(sys.stdin.buffer)
    channel = Channel()
    if config.get("checkpoint_probe"):
        config["agent_options"]["boundary_hook"] = lambda event, tool: channel.call("boundary", event=event, tool=tool)
    state = run_agent(Model(channel, config["model"]), Toolbox(channel, config),
                      Path("/workspace/agent-state.json"), **config["agent_options"])
    write_frame(sys.stdout.buffer, {"method": "result", "result": {
        key: state.get(key) for key in ("status", "reason", "usage", "terminal", "resume_count",
                                      "error_type", "provider_status_code")}})


if __name__ == "__main__":
    main()
