package web

import (
	"embed"
	"io/fs"
	"net/http"
)

//go:embed index.html app.js style.css
var assets embed.FS

func Handler() http.Handler {
	sub, _ := fs.Sub(assets, ".")
	return http.FileServer(http.FS(sub))
}
