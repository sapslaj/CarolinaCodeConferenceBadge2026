# Build context is the repo root, not server/, so the image can bundle
# samples/ for OTA:
#   docker build -f server/Dockerfile -t oci.sapslaj.xyz/badge-hub .

FROM golang:1.26 AS build
WORKDIR /src
COPY server/ ./
RUN CGO_ENABLED=0 go build -o /badge-server .

FROM gcr.io/distroless/static-debian12
COPY --from=build /badge-server /badge-server
COPY samples/ /samples
ENTRYPOINT ["/badge-server"]
