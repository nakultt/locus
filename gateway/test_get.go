package main

import (
	"fmt"
	"net/http"
)

func main() {
	resp, err := http.Get("http://localhost:8080/auth/login")
	if err != nil {
		fmt.Println("Error:", err)
		return
	}
	fmt.Println("Status Code:", resp.StatusCode)
}
