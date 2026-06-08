package main

import (
	"fmt"
	"net/http"

	"github.com/go-chi/chi/v5"
)

func main() {
	r := chi.NewRouter()

	r.Post("/auth/login", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("post login"))
	})

	r.MethodNotAllowed(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("custom method not allowed!"))
	})

	r.NotFound(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("not found!"))
	})

	fmt.Println("Listening on :8888")
	http.ListenAndServe(":8888", r)
}
