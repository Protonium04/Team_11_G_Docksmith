package models

// LayerEntry describes one layer in an image manifest.
type LayerEntry struct {
	Digest    string `json:"digest"`
	Size      int64  `json:"size"`
	CreatedBy string `json:"createdBy"`
}

// ImageConfig holds runtime configuration embedded in a manifest.
type ImageConfig struct {
	Env        []string `json:"Env"`
	Cmd        []string `json:"Cmd"`
	WorkingDir string   `json:"WorkingDir"`
}

// ImageManifest is the top-level JSON document stored in ~/.docksmith/images/.
type ImageManifest struct {
	Name    string       `json:"name"`
	Tag     string       `json:"tag"`
	Digest  string       `json:"digest"`
	Created string       `json:"created"`
	Config  ImageConfig  `json:"config"`
	Layers  []LayerEntry `json:"layers"`
}
