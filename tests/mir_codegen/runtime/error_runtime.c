#include <stdlib.h>
#include <string.h>
#include <stdio.h>

struct Error {
    char* json;
};

struct Error* error_new(const char* msg) {
    struct Error* err = (struct Error*)malloc(sizeof(struct Error));
    if (!err) return NULL;
    size_t len = strlen(msg);
    size_t json_len = len + 10; // enough for {"msg":""}
    err->json = (char*)malloc(json_len + 1);
    if (!err->json) { free(err); return NULL; }
    snprintf(err->json, json_len + 1, "{\"msg\":\"%s\"}", msg);
    return err;
}

const char* error_to_cstr(struct Error* err) {
    if (!err) return NULL;
    return err->json;
}

void error_free(struct Error* err) {
    if (!err) return;
    free(err->json);
    free(err);
}
