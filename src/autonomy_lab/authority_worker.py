"""Private broker/verifier processes. Never loaded in the agent image."""

import sys
import uuid
from pathlib import Path

from autonomy_lab.broker import ActionBroker, BrokerPolicy
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import Kubernetes
from autonomy_lab.rpc import error_record, read_frame, write_frame
from autonomy_lab.verifier import verify


class OperationNotFound(KeyError):
    pass


def main():
    config = read_frame(sys.stdin.buffer)
    kube = Kubernetes(Path(config["kubeconfig"]), config["cluster_name"], config["namespace"])
    if config["role"] == "broker":
        class Adapter:
            def get_service(self, namespace, name):
                return kube.get_service(namespace, name)

            def patch_service(self, namespace, name, patch):
                response = kube.patch_service(namespace, name, patch)
                if config["withhold_ack"]:
                    save(Path(config["response_loss_path"]), {"resource_version": response["metadata"]["resourceVersion"]})
                    raise TimeoutError("controlled response loss after actual mutation")
                return response

        broker = ActionBroker(Path(config["journal"]), BrokerPolicy(**config["policy"]), Adapter())
    while True:
        try:
            request = read_frame(sys.stdin.buffer)
        except ValueError:
            return
        try:
            if config["role"] == "broker":
                if request["method"] not in {"propose", "lookup", "reconcile", "events"}:
                    raise ValueError("Unknown broker method")
                if request["method"] == "propose":
                    kube.audit_operation_id = request["argument"]["operation_id"]
                if request["method"] == "lookup":
                    try:
                        result = broker.lookup(request["argument"])
                    except KeyError:
                        raise OperationNotFound from None
                else:
                    result = getattr(broker, request["method"])(request["argument"])
            elif config["role"] == "verifier" and request["method"] == "verify":
                config["verification"]["expectations_path"] = Path(config["verification"]["expectations_path"])
                result = verify(**config["verification"], service_reader=lambda: kube.get_service(kube.namespace, "inventory"))
                save(Path(config["run_dir"]) / f"verification-{uuid.uuid4().hex}.json", result)
            else:
                raise ValueError("Unknown authority method")
            response = {"result": result}
        except Exception as error:
            response = {"error": error_record(error)}
        response["id"] = request.get("id")
        write_frame(sys.stdout.buffer, response)


if __name__ == "__main__":
    main()
