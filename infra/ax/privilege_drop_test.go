package substrate

import (
	"reflect"
	"testing"
)

func TestLabBootstrapCapabilitiesAreScoped(t *testing.T) {
	lab := BuildActorTemplate("autonomy-agents", "task", "image", nil, nil, "bucket")
	got := lab.Containers[0].GetSecurityContext().GetCapabilities().GetAdd()
	if !reflect.DeepEqual(got, []string{"CHOWN", "SETUID", "SETGID"}) {
		t.Fatalf("unexpected bootstrap capabilities: %v", got)
	}
	normal := BuildActorTemplate("other", "task", "image", nil, nil, "bucket")
	if normal.Containers[0].GetSecurityContext() != nil {
		t.Fatal("capability adjustment escaped the lab atespace")
	}
}
