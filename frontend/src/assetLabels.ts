import type { AssetType } from "./types";

export const TYPE_LABEL: Record<AssetType, string> = {
  logo: "Logo",
  banner: "Banner",
  social_square: "Social Square",
  product_mockup: "Product Mockup",
  business_card: "Business Card",
};

export function assetLabel(type: AssetType): string {
  return TYPE_LABEL[type] ?? type;
}
