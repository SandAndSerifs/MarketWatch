"use client";
import { useParams } from "next/navigation";
import TradeReview from "@/components/TradeReview";

export default function TradePage() {
  const { id } = useParams<{ id: string }>();
  return <TradeReview id={Number(id)} />;
}
