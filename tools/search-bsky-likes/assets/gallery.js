const response = await fetch("/posts.json");
if (!response.ok) throw new Error(`Could not load posts: ${response.status}`);
const posts = await response.json();

document.querySelector("#summary").textContent = `${posts.length} liked media posts`;
const container = document.querySelector("#posts");

for (const post of posts) {
  const article = document.createElement("article");
  const link = document.createElement("a");
  link.href = post.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";

  const preview = findImage(post.embed);
  if (preview?.url) {
    const image = document.createElement("img");
    image.src = preview.url;
    image.loading = "lazy";
    image.alt = preview.alt;
    link.append(image);
  }

  const text = document.createElement("p");
  text.textContent = post.text || "View post";
  link.append(text);
  article.append(link);
  container.append(article);
}

function findImage(embed) {
  if (!embed || typeof embed !== "object") return undefined;
  if (Array.isArray(embed.images) && embed.images[0]) {
    const image = embed.images[0];
    return {
      url: image.thumb ?? image.fullsize,
      alt: typeof image.alt === "string" ? image.alt : "",
    };
  }
  if (embed.thumbnail) return { url: embed.thumbnail, alt: "" };
  if (embed.external?.thumb) return { url: embed.external.thumb, alt: "" };
  return findImage(embed.media);
}
