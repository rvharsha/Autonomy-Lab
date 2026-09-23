package controller

import (
	"github.com/google/ax/pkg/apis/v1alpha1"
	"google.golang.org/protobuf/types/known/timestamppb"
	"testing"
)

func TestRuntimeTaskStableAcrossLifecycle(t *testing.T) {
	task := &v1alpha1.Task{
		Metadata: &v1alpha1.ObjectMeta{Name: "job", Atespace: "lab"},
		Spec:     &v1alpha1.TaskSpec{Image: "registry/task@sha256:abc", Command: []string{"python", "agent.py"}},
	}
	initial, err := runtimeTaskYAML(task)
	if err != nil {
		t.Fatal(err)
	}
	task.Status = &v1alpha1.TaskStatus{Phase: "Running", WorkerIp: "10.0.0.1"}
	task.Metadata.CreationTimestamp = timestamppb.Now()
	task.Spec.Suspend = true
	paused, err := runtimeTaskYAML(task)
	if err != nil {
		t.Fatal(err)
	}
	if string(paused) != string(initial) {
		t.Fatal("lifecycle creates a new execution template")
	}
	if !task.Spec.Suspend || task.Status == nil {
		t.Fatal("input task was modified")
	}
	task.Spec.Command = []string{"python", "different.py"}
	changed, err := runtimeTaskYAML(task)
	if err != nil {
		t.Fatal(err)
	}
	if string(changed) == string(initial) {
		t.Fatal("execution change lost")
	}
}
