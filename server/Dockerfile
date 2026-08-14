FROM golang:1.26 AS build
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -o /badge-server .

FROM gcr.io/distroless/static-debian12
COPY --from=build /badge-server /badge-server
ENTRYPOINT ["/badge-server"]
