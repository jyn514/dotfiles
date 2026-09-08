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

  const imageUrl = findImage(post.embed);
  if (imageUrl) {
    const image = document.createElement("img");
    image.src = imageUrl;
    image.loading = "lazy";
    image.alt = "";
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
    return embed.images[0].thumb ?? embed.images[0].fullsize;
  }
  if (embed.thumbnail) return embed.thumbnail;
  if (embed.external?.thumb) return embed.external.thumb;
  return findImage(embed.media);
}
